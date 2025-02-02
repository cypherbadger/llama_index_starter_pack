import os
import streamlit as st
from streamlit_chat import message as st_message
from sqlalchemy import create_engine

from langchain.agents import Tool, initialize_agent
from langchain.chains.conversation.memory import ConversationBufferMemory

from llama_index import GPTSQLStructStoreIndex, LLMPredictor
from llama_index import SQLDatabase as llama_SQLDatabase
from llama_index.indices.struct_store import SQLContextContainerBuilder

from constants import (
    DEFAULT_SQL_PATH,
    DEFAULT_BUSINESS_TABLE_DESCRP,
    DEFAULT_VIOLATIONS_TABLE_DESCRP,
    DEFAULT_INSPECTIONS_TABLE_DESCRP,
    DEFAULT_LC_TOOL_DESCRP
)
from utils import get_sql_index_tool, get_llm

# NOTE: for local testing only, do NOT deploy with your key hardcoded
# to use this for yourself, create a file called .streamlit/secrets.toml with your api key
# Learn more about Streamlit on the docs: https://docs.streamlit.io/
os.environ["OPENAI_API_KEY"] = st.secrets["openai_api_key"]


@st.cache_resource
def initialize_index(llm_name, model_temperature, table_context_dict, sql_path=DEFAULT_SQL_PATH):
    """Create the GPTSQLStructStoreIndex object."""
    llm = get_llm(llm_name, model_temperature)

    engine = create_engine(sql_path)
    sql_database = llama_SQLDatabase(engine)

    context_container = None
    if table_context_dict is not None:
        context_builder = SQLContextContainerBuilder(sql_database, context_dict=table_context_dict)
        context_container = context_builder.build_context_container()

    index = GPTSQLStructStoreIndex([], 
                                   sql_database=sql_database, 
                                   sql_context_container=context_container, 
                                   llm_predictor=LLMPredictor(llm=llm))

    return index


@st.cache_resource
def initialize_chain(llm_name, model_temperature, lc_descrp, _sql_index):
    """Create a (rather hacky) custom agent and sql_index tool."""
    sql_tool = Tool(name="SQL Index", 
                    func=get_sql_index_tool(_sql_index, _sql_index.sql_context_container.context_dict), 
                    description=lc_descrp)

    llm = get_llm(llm_name, model_temperature)

    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

    agent_chain = initialize_agent([sql_tool], llm, agent="chat-conversational-react-description", verbose=True, memory=memory)

    return agent_chain


st.title("🦙 Llama Index SQL Sandbox 🦙")
st.markdown((
    "This sandbox uses a sqlite database by default, containing information on health violations and inspections at restaurants in San Francisco.\n\n"
    "The database contains three tables - businesses, inspections, and violations.\n\n"
    "Using the setup page, you can adjust LLM settings, change the context for the SQL tables, and change the tool description for Langchain."
))


setup_tab, llama_tab, lc_tab = st.tabs(["Setup", "Llama Index", "Langchain+Llama Index"])

with setup_tab:
    st.subheader("LLM Setup")
    model_temperature = st.slider("LLM Temperature", min_value=0.0, max_value=1.0, step=0.1)
    llm_name = st.selectbox('Which LLM?', ["text-davinci-003", "gpt-3.5-turbo", "gpt-4"])
    
    st.subheader("Table Setup")
    business_table_descrp = st.text_area("Business table description", value=DEFAULT_BUSINESS_TABLE_DESCRP)
    violations_table_descrp = st.text_area("Business table description", value=DEFAULT_VIOLATIONS_TABLE_DESCRP)
    inspections_table_descrp = st.text_area("Business table description", value=DEFAULT_INSPECTIONS_TABLE_DESCRP)

    table_context_dict = {"businesses": business_table_descrp, 
                          "inspections": inspections_table_descrp, 
                          "violations": violations_table_descrp}
    
    use_table_descrp = st.checkbox("Use table descriptions?", value=True)
    lc_descrp = st.text_area("LangChain Tool Description", value=DEFAULT_LC_TOOL_DESCRP)

with llama_tab:
    st.subheader("Text2SQL with Llama Index")
    if st.button("Initialize Index", key="init_index_1"):
        st.session_state['llama_index'] = initialize_index(llm_name, model_temperature, table_context_dict if use_table_descrp else None)
    
    if "llama_index" in st.session_state:
        query_text = st.text_input("Query:")
        if st.button("Run Query") and query_text:
            with st.spinner("Getting response..."):
                try:
                    response =  st.session_state['llama_index'].query(query_text)
                    response_text = str(response)
                    response_sql = response.extra_info['sql_query']
                except Exception as e:
                    response_text = "Error running SQL Query."
                    response_sql = str(e)

            col1, col2 = st.columns(2)
            with col1:
                st.text("SQL Result:")
                st.markdown(response_text)

            with col2:
                st.text("SQL Query:")
                st.markdown(response_sql)

with lc_tab:
    st.subheader("Langchain + Llama Index SQL Demo")

    if st.button("Initialize Agent"):
        st.session_state['llama_index'] = initialize_index(llm_name, model_temperature, table_context_dict if use_table_descrp else None)
        st.session_state['lc_agent'] = initialize_chain(llm_name, model_temperature, lc_descrp, st.session_state['llama_index'])
        st.session_state['chat_history'] = []

    model_input = st.text_input("Message:")
    if 'lc_agent' in st.session_state and st.button("Send"):
        model_input = "User: " + model_input
        st.session_state['chat_history'].append(model_input)
        with st.spinner("Getting response..."):
            response =  st.session_state['lc_agent'].run(input=model_input)
        st.session_state['chat_history'].append(response)

    if 'chat_history' in st.session_state:
        for msg in st.session_state['chat_history']:
            st_message(msg.split("User: ")[-1], is_user="User: " in msg)
        