import asyncio

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import run_agent


def show(message):
    """Draw one message in the chat."""
    if isinstance(message, HumanMessage):
        st.chat_message("user").write(message.content)
    elif isinstance(message, ToolMessage):
        st.chat_message("assistant").code(f"{message.name} result:\n{message.content}")
    elif isinstance(message, AIMessage):
        for call in message.tool_calls:
            st.chat_message("assistant").code(f"{call['name']}({call['args']})")
        if message.content:
            st.chat_message("assistant").write(message.content)


st.title("MCP Chat")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    show(message)

if prompt := st.chat_input("Message"):
    st.session_state.messages.append(HumanMessage(prompt))
    show(st.session_state.messages[-1])
    old_count = len(st.session_state.messages)
    with st.spinner("Thinking..."):
        st.session_state.messages = asyncio.run(run_agent(st.session_state.messages))
    for message in st.session_state.messages[old_count:]:
        show(message)
