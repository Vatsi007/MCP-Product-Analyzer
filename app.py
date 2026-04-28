import json
import asyncio
from contextlib import AsyncExitStack
import chainlit as cl
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
from google import genai
from google.genai import types

def convert_json_schema_to_gemini(schema):
    """Recursively converts a standard JSON schema into Gemini's expected Schema dict format."""
    if not isinstance(schema, dict):
        return schema
        
    new_schema = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            new_schema[k] = v.upper() # Gemini expects uppercase types like "STRING", "OBJECT"
        elif k == "title" or k == "default":
            continue # Skip fields Gemini might complain about
        elif isinstance(v, dict):
            new_schema[k] = convert_json_schema_to_gemini(v)
        elif isinstance(v, list):
            new_schema[k] = [convert_json_schema_to_gemini(i) for i in v]
        else:
            new_schema[k] = v
    return new_schema

def get_gemini_tools(mcp_tools):
    gemini_funcs = []
    for t in mcp_tools.tools:
        gemini_funcs.append(
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=convert_json_schema_to_gemini(t.inputSchema)
            )
        )
    return [types.Tool(function_declarations=gemini_funcs)]

@cl.on_chat_start
async def on_chat_start():
    # 1. Ask for API Key
    res = await cl.AskUserMessage(
        content="Welcome to the Price Compare AI! 🛍️\n\nPlease enter your Google Gemini API key to begin. *(Your key is only stored in memory for this session and will be deleted when you refresh or close the tab)*",
        timeout=300
    ).send()
    
    if not res:
        await cl.Message(content="Session timed out. Please refresh to try again.").send()
        return
        
    api_key = res['output']
    client = genai.Client(api_key=api_key)
    cl.user_session.set("gemini_client", client)
    
    await cl.Message(content="✅ API Key accepted! Connecting to local MCP Server...").send()
    
    # 2. Connect to local MCP Server
    stack = AsyncExitStack()
    cl.user_session.set("mcp_stack", stack)
    
    try:
        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        server_params = StdioServerParameters(command="python", args=["mcp_server.py"], env=env)
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read, write = stdio_transport
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        
        # 3. Discover Tools
        mcp_tools = await session.list_tools()
        cl.user_session.set("mcp_session", session)
        cl.user_session.set("mcp_tools", mcp_tools)
        
        # Initialize Gemini Chat
        system_prompt = """You are a premium AI shopping assistant. Use the available tools to fetch live data from Amazon and Flipkart.
        
        CRITICAL FORMATTING RULES:
        1. NEVER output raw, long URLs in your final response. ALWAYS hide them behind clean Markdown links (e.g., [View on Amazon](url)).
        2. When a tool returns data (like specs, prices, and winners), present it beautifully using bullet points, bold text, and emojis.
        3. Do not just summarize the tool output—recreate the detailed comparison in a visually pleasing way so the user doesn't have to open the tool logs."""
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=get_gemini_tools(mcp_tools),
            temperature=0.0
        )
        chat = client.chats.create(model="gemini-2.5-flash", config=config)
        cl.user_session.set("gemini_chat", chat)
        
        # 4. Display Tools in Sidebar
        sidebar_content = "### Available MCP Tools\n\n"
        for t in mcp_tools.tools:
            sidebar_content += f"**🔧 {t.name}**\n_{t.description}_\n\n---\n"
            
        elements = [
            cl.Text(name="Available Tools", content=sidebar_content, display="side")
        ]
        
        await cl.Message(
            content="🎉 Connected successfully! Click on 'Available Tools' (or check the sidebar) to see what I can do.\n\nHow can I help you find the best deals today?", 
            elements=elements
        ).send()
        
    except Exception as e:
        await cl.Message(content=f"❌ Failed to connect to MCP server: {e}").send()


@cl.on_message
async def on_message(message: cl.Message):
    chat = cl.user_session.get("gemini_chat")
    mcp_session = cl.user_session.get("mcp_session")
    
    if not chat or not mcp_session:
        await cl.Message(content="Session is not fully initialized. Please refresh the page.").send()
        return

    # Create a processing step in Chainlit
    msg = cl.Message(content="")
    await msg.send()
    
    async def retry_send_message(content, max_retries=5):
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(chat.send_message, content)
            except Exception as e:
                if "503" in str(e) and attempt < max_retries - 1:
                    await cl.Message(content=f"⏳ Server is busy (503). Retrying in {2**attempt} seconds... (Attempt {attempt+1}/{max_retries})").send()
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise e
    
    try:
        # Send the initial message with automatic retry
        response = await retry_send_message(message.content)
        
        # Process potential tool calls loop
        while response.function_calls:
            for fc in response.function_calls:
                # Tell user we are calling a tool
                async with cl.Step(name=f"Tool: {fc.name}") as step:
                    step.input = fc.args
                    
                    try:
                        # Call local MCP Server
                        mcp_result = await mcp_session.call_tool(fc.name, arguments=fc.args)
                        
                        # Format result to string
                        if getattr(mcp_result, 'content', None):
                            result_str = "\n".join([c.text for c in mcp_result.content if c.type == "text"])
                        else:
                            result_str = str(mcp_result)
                            
                        step.output = result_str
                        
                    except Exception as e:
                        result_str = f"Error calling tool: {str(e)}"
                        step.output = result_str
                        step.is_error = True
                        
                # Send tool response back to Gemini with automatic retry
                response = await retry_send_message(
                    [types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result_str}
                    )]
                )
                
        msg.content = response.text or "Done."
        await msg.update()
        
    except Exception as e:
        msg.content = f"An error occurred: {str(e)}"
        await msg.update()

@cl.on_chat_end
async def on_chat_end():
    stack = cl.user_session.get("mcp_stack")
    if stack:
        await stack.aclose()
