import os
import streamlit as st
import time
import asyncio
from typing import List, Dict, Any, Optional
import markdown
import langchain
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI

from open_deep_research.configuration import Configuration, SearchAPI
from open_deep_research.graph import (
    generate_report_plan,
    generate_queries,
    search_web,
    write_section,
    gather_completed_sections,
    write_final_sections,
    compile_final_report
)

# Add fallback direct content creation function
def create_direct_section_content(state, config):
    """Fallback function that directly uses the LLM to generate section content when the standard process fails."""
    try:
        # Get the topic, section and search results
        topic = state.get("topic", "")
        section = state.get("section")
        source_str = state.get("source_str", "")
        
        # Validate input data
        if not section or not source_str:
            raise ValueError("Missing required data for direct content creation")
        
        # Get the model configuration
        model_name = config.get("configurable", {}).get("writer_model", "gemini-1.5-pro-latest")
        
        # Ensure Google API key is set
        google_api_key = os.environ.get("GOOGLE_API_KEY")
        if not google_api_key:
            raise ValueError("Google API key is required for direct content creation")
            
        # Create the LLM
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.5,
            convert_system_message_to_human=True,
            max_output_tokens=4096,
            safety_settings={
                "HARASSMENT": "block_none",
                "HATE": "block_none",
                "SEXUAL": "block_none",
                "DANGEROUS": "block_none"
            }
        )
        
        # Prepare the prompt
        prompt = f"""You are writing a detailed section for a research report on the topic: '{topic}'.

Section: '{section.name}'
Section Description: '{section.description}'

Below are the research results from web searches on this topic. Use this information to write a comprehensive, well-structured section:

{source_str}

Instructions:
1. Write a detailed, informative section based ONLY on the research results above.
2. Include relevant facts, insights, and analysis from the source material.
3. Organize the content with appropriate subheadings if needed.
4. Focus on accuracy and completeness.
5. Format the content with markdown syntax.
6. Keep your response focused only on writing the content - do not include any preamble, explanation, or conclusion about your writing process.

Write the section content now:"""
        
        # Generate content
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        
        # Check if content is valid
        if not content or len(content) < 100:
            raise ValueError("Generated content is too short or empty")
        
        # Create section object with new content
        from open_deep_research.state import Section
        completed_section = Section(
            name=section.name,
            description=section.description,
            research=True,
            content=content
        )
        
        # Return in the expected format
        return {"completed_sections": [completed_section]}
    except Exception as e:
        import traceback
        print(f"Error in direct content creation: {str(e)}")
        print(traceback.format_exc())
        # Return a string instead of raising to allow graceful failure
        return f"## {section.name}\n\nUnable to generate complete content for this section due to technical issues.\n\nPlease try again later or modify the section scope.\n\nError details: {str(e)}"

from open_deep_research.state import (
    ReportState,
    SectionState,
    Section,
    SearchQuery
)
from open_deep_research.utils import format_sections, select_and_execute_search, get_search_params, get_config_value

# Function to load environment variables from .env file if it exists
def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception as e:
        st.warning(f"Could not load .env file: {e}")

# Set page configuration
st.set_page_config(
    page_title="Deep Research Agent",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better appearance
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .status-box {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .status-running {
        background-color: #f0f2f6;
        border-left: 0.5rem solid #ffd166;
    }
    .status-complete {
        background-color: #f0f7f0;
        border-left: 0.5rem solid #06d6a0;
    }
    .content-box {
        background-color: #f7f7f7;
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .section-title {
        font-size: 1.2rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .footer {
        text-align: center;
        margin-top: 2rem;
        color: #888;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state for storing the research state and progress
if 'initialized' not in st.session_state:
    st.session_state.initialized = False
    st.session_state.topic = ""
    st.session_state.report_plan = None
    st.session_state.sections = []
    st.session_state.completed_sections = []
    st.session_state.section_progress = {}
    st.session_state.final_report = ""
    st.session_state.current_step = "input"
    st.session_state.config = None
    st.session_state.feedback = None

def initialize_config(topic, report_structure, search_api, planner_model, writer_model, max_search_depth):
    """Initialize configuration for the research agent"""
    
    search_api_enum = getattr(SearchAPI, search_api.upper(), SearchAPI.TAVILY)
    
    # Create configuration
    config = Configuration(
        report_structure=report_structure,
        number_of_queries=5,
        max_search_depth=max_search_depth,
        planner_provider="google_genai",
        planner_model=planner_model,
        writer_provider="google_genai",
        writer_model=writer_model,
        search_api=search_api_enum,
        max_token=30000,
    )
    
    runnable_config = {
        "configurable": {
            "report_structure": config.report_structure,
            "number_of_queries": config.number_of_queries,
            "max_search_depth": config.max_search_depth,
            "planner_provider": config.planner_provider,
            "planner_model": config.planner_model,
            "writer_provider": config.writer_provider,
            "writer_model": config.writer_model,
            "search_api": config.search_api,
            "max_token": config.max_token,
        }
    }
    
    st.session_state.config = runnable_config
    return runnable_config

# Main app layout
def main():
    # Load environment variables
    load_env()
    
    # Sidebar for configuration
    with st.sidebar:
        st.title("Deep Research Configuration")
        
        # API keys section (collapsed by default)
        with st.expander("API Keys (Required)"):
            google_api_key = st.text_input("Google API Key (for Gemini)", type="password", 
                                          value=os.environ.get("GOOGLE_API_KEY", ""))
            if google_api_key:
                os.environ["GOOGLE_API_KEY"] = google_api_key
            
            search_api_key = st.text_input("Search API Key (Tavily/Exa)", type="password",
                                         value=os.environ.get("TAVILY_API_KEY", ""))
            if search_api_key:
                os.environ["TAVILY_API_KEY"] = search_api_key
        
        # Model selection
        st.subheader("Model Configuration")
        planner_model = st.selectbox(
            "Planner Model",
            ["gemini-2.5-pro-exp-03-25", "claude-3-7-sonnet-latest"],
            index=0
        )
        
        writer_model = st.selectbox(
            "Writer Model",
            ["gemini-2.5-pro-exp-03-25", "claude-3-5-sonnet-latest"],
            index=0
        )
        
        # Search configuration
        st.subheader("Search Configuration")
        search_api = st.selectbox(
            "Search API",
            ["TAVILY", "EXA", "DUCKDUCKGO", "GOOGLESEARCH"],
            index=0
        )
        
        max_search_depth = st.slider(
            "Max Search Depth",
            min_value=1,
            max_value=5,
            value=3,
            help="Maximum number of search iterations per section"
        )
        
        # Reset button
        if st.button("Reset Research"):
            # Reset session state
            for key in list(st.session_state.keys()):
                if key != "initialized":
                    del st.session_state[key]
            st.session_state.current_step = "input"
            st.rerun()
    
    # Main content area
    st.title("🔍 Deep Research Agent")
    
    # Step 1: Input topic and start research
    if st.session_state.current_step == "input":
        st.markdown("### Research Topic")
        topic = st.text_area("Enter the topic you want to research", height=100,
                           placeholder="Example: The impacts of artificial intelligence on modern healthcare")
        
        # Advanced options (collapsed by default)
        with st.expander("Advanced Options"):
            report_structure = st.text_area(
                "Report Structure", 
                Configuration().report_structure,
                height=200
            )
        
        # Start button
        if st.button("Start Research", type="primary", disabled=not topic):
            if not google_api_key:
                st.error("Please enter a Google API Key in the sidebar.")
            elif not search_api_key and search_api in ["TAVILY", "EXA"]:
                st.error(f"Please enter a {search_api} API Key in the sidebar.")
            else:
                # Initialize config and start research
                st.session_state.topic = topic
                runnable_config = initialize_config(
                    topic=topic,
                    report_structure=report_structure,
                    search_api=search_api,
                    planner_model=planner_model,
                    writer_model=writer_model,
                    max_search_depth=max_search_depth
                )
                st.session_state.current_step = "generate_plan"
                st.rerun()
    
    # Step 2: Generate report plan
    elif st.session_state.current_step == "generate_plan":
        st.markdown("### Generating Report Plan")
        
        # Check for required API keys before proceeding
        google_api_key = os.environ.get("GOOGLE_API_KEY", "")
        search_api = st.session_state.config.get("configurable", {}).get("search_api", "TAVILY")
        search_api_key = ""
        
        if isinstance(search_api, SearchAPI):
            search_api_str = search_api.value
        else:
            search_api_str = str(search_api)
            
        if search_api_str.upper() == "TAVILY":
            search_api_key = os.environ.get("TAVILY_API_KEY", "")
        elif search_api_str.upper() == "EXA":
            search_api_key = os.environ.get("EXA_API_KEY", "")
        
        # Validate required keys
        missing_keys = []
        if not google_api_key:
            missing_keys.append("Google API Key")
        if search_api_str.upper() in ["TAVILY", "EXA"] and not search_api_key:
            missing_keys.append(f"{search_api_str} API Key")
        
        if missing_keys:
            st.error(f"Missing required API keys: {', '.join(missing_keys)}")
            st.info("Please enter the required API keys in the sidebar and try again.")
            # Add a button to go back to input step
            if st.button("Back to Start"):
                st.session_state.current_step = "input"
                st.rerun()
            return
            
        with st.status("Generating report plan...", expanded=True) as status:
            try:
                # Create initial state
                state: ReportState = {"topic": st.session_state.topic}
                if st.session_state.feedback is not None:
                    state["feedback_on_report_plan"] = st.session_state.feedback
                
                # Generate report plan with timeout protection
                with st.spinner("Generating queries and searching for context..."):
                    try:
                        # Set a reasonable timeout to prevent hanging
                        result = asyncio.run(generate_report_plan(state, st.session_state.config))
                        
                        # Validate result has expected structure
                        if not result or "sections" not in result or not result["sections"]:
                            raise ValueError("Failed to generate a valid report plan with sections")
                            
                        # Update session state
                        st.session_state.sections = result.get("sections", [])
                        st.session_state.report_plan = result
                        st.session_state.current_step = "review_plan"
                        
                        # Mark as complete
                        status.update(label="Report plan generated successfully!", state="complete")
                        time.sleep(1)
                        st.rerun()
                    except asyncio.TimeoutError:
                        st.error("Operation timed out. The model or search API may be experiencing issues.")
                        status.update(label="Timeout Error", state="error")
                    except Exception as e:
                        st.error(f"Error during report generation: {str(e)}")
                        status.update(label=f"Error: {str(e)}", state="error")
            except Exception as e:
                st.error(f"Error generating report plan: {str(e)}")
                status.update(label=f"Error: {str(e)}", state="error")
                
            # Add retry button if there was an error
            if status.state == "error":
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Retry"):
                        st.rerun()
                with col2:
                    if st.button("Back to Start"):
                        st.session_state.current_step = "input"
                        st.rerun()
    
    # Step 3: Review plan and provide feedback
    elif st.session_state.current_step == "review_plan":
        st.markdown("### Review Report Plan")
        
        # Display sections
        for idx, section in enumerate(st.session_state.sections, 1):
            with st.expander(f"Section {idx}: {section.name}", expanded=True):
                st.markdown(f"**Description:** {section.description}")
                st.markdown(f"**Requires Research:** {'Yes' if section.research else 'No'}")
        
        # Feedback options with better UI flow
        st.markdown("### Approve or Modify Plan")
        
        # Add a feedback mode to session state if not present
        if 'feedback_mode' not in st.session_state:
            st.session_state.feedback_mode = False
            
        # Create two columns for the buttons
        col1, col2 = st.columns(2)
        
        # Only show the approve button if not in feedback mode
        if not st.session_state.feedback_mode:
            with col1:
                if st.button("Approve Plan", type="primary"):
                    # Reset feedback state
                    st.session_state.feedback = None
                    st.session_state.current_step = "research_sections"
                    st.rerun()
            
            with col2:
                if st.button("Modify Plan"):
                    st.session_state.feedback_mode = True
                    st.rerun()
        
        # Show feedback input if in feedback mode
        if st.session_state.feedback_mode:
            st.write("Please provide specific feedback to improve the report plan:")
            
            # Initialize feedback in session state if not present
            if 'feedback_text' not in st.session_state:
                st.session_state.feedback_text = ""
            
            # Use a callback to update feedback text
            def update_feedback():
                st.session_state.feedback_text = st.session_state.feedback_input
                
            # Text area with session state binding
            feedback = st.text_area(
                "Your feedback",
                key="feedback_input",
                value=st.session_state.feedback_text,
                placeholder="Example: Add a section about ethical considerations. Make the focus more on healthcare applications.",
                height=120,
                on_change=update_feedback
            )
            
            col3, col4 = st.columns(2)
            with col3:
                if st.button("Submit Feedback", type="primary", disabled=not feedback):
                    # Store feedback and regenerate plan
                    st.session_state.feedback = feedback
                    st.session_state.feedback_mode = False
                    st.session_state.current_step = "generate_plan"
                    st.rerun()
            
            with col4:
                if st.button("Cancel"):
                    # Reset feedback mode
                    st.session_state.feedback_mode = False
                    st.rerun()
    
    # Step 4: Research sections
    elif st.session_state.current_step == "research_sections":
        st.markdown("### Researching Sections")
        
        # Initialize section progress if needed
        if not st.session_state.section_progress:
            for section in st.session_state.sections:
                if section.research:
                    st.session_state.section_progress[section.name] = {
                        "status": "pending",
                        "iterations": 0,
                        "search_queries": [],
                        "source_str": "",
                        "completed": False
                    }
        
        # Count total and completed sections
        total_research_sections = sum(1 for section in st.session_state.sections if section.research)
        completed_sections = sum(1 for section_name, progress in st.session_state.section_progress.items() 
                                        if progress.get("completed", False))
        
        # Progress bar
        st.progress(completed_sections / total_research_sections if total_research_sections > 0 else 0)
        
        # Process each section that needs research
        all_completed = True
        
        for section in st.session_state.sections:
            if not section.research:
                continue
            
            section_name = section.name
            progress = st.session_state.section_progress.get(section_name, {})
            
            if progress.get("completed", False):
                st.success(f"Section: {section_name} (Completed)")
                with st.expander("View Content", expanded=False):
                    st.markdown(section.content)
                continue
            
            all_completed = False
            
            st.subheader(f"Section: {section_name} (In Progress)")
            status = progress.get("status", "pending")
            
            if status == "pending":
                # Start processing this section
                st.info(f"Starting research for '{section_name}'")
                
                # Update status
                st.session_state.section_progress[section_name]["status"] = "generating_queries"
                st.rerun()
                
            elif status == "generating_queries":
                st.info(f"Generating search queries for '{section_name}'")
                
                # Verify API keys are set before proceeding
                google_api_key = os.environ.get("GOOGLE_API_KEY", "")
                if not google_api_key:
                    st.error("Missing Google API Key - required for generating queries")
                    st.session_state.section_progress[section_name]["status"] = "error"
                    continue
                
                try:
                    # Create section state
                    section_state: SectionState = {
                        "topic": st.session_state.topic,
                        "section": section,
                        "search_iterations": progress.get("iterations", 0),
                        "search_queries": progress.get("search_queries", []),
                        "source_str": progress.get("source_str", ""),
                        "report_sections_from_research": "",
                        "completed_sections": []
                    }
                    
                    st.write(f"Using model: {st.session_state.config.get('configurable', {}).get('writer_model', 'Not specified')}")
                    try:
                        # Set a timeout for the query generation
                        result = generate_queries(section_state, st.session_state.config)
                        
                        # Verify we have search queries
                        search_queries = result.get("search_queries", [])
                        if not search_queries:
                            raise ValueError("No search queries were generated")
                            
                        # Update progress
                        st.session_state.section_progress[section_name]["search_queries"] = search_queries
                        st.session_state.section_progress[section_name]["status"] = "searching_web"
                        
                        # Show queries
                        st.write("Generated search queries:")
                        for q in search_queries:
                            st.write(f"- {q.search_query}")
                            
                        st.success("Queries generated successfully")
                        time.sleep(1)
                        st.rerun()
                    except Exception as inner_e:
                        import traceback
                        error_details = traceback.format_exc()
                        st.error(f"Error generating queries: {str(inner_e)}")
                        st.code(error_details, language="python")
                        st.session_state.section_progress[section_name]["status"] = "error"
                except Exception as e:
                    import traceback
                    st.error(f"Error in query generation process: {str(e)}")
                    st.code(traceback.format_exc(), language="python")
                    st.session_state.section_progress[section_name]["status"] = "error"
                
            elif status == "searching_web":
                st.info(f"Searching the web for '{section_name}'")
                
                # Check search API configuration
                search_api = st.session_state.config.get("configurable", {}).get("search_api", "TAVILY")
                search_api_key = ""
                
                if isinstance(search_api, SearchAPI):
                    search_api_str = search_api.value
                else:
                    search_api_str = str(search_api)
                    
                # Verify API keys for search
                if search_api_str.upper() == "TAVILY":
                    search_api_key = os.environ.get("TAVILY_API_KEY", "")
                    if not search_api_key:
                        st.error("Missing Tavily API Key required for web search")
                        st.session_state.section_progress[section_name]["status"] = "error"
                        continue
                elif search_api_str.upper() == "EXA":
                    search_api_key = os.environ.get("EXA_API_KEY", "")
                    if not search_api_key:
                        st.error("Missing Exa API Key required for web search")
                        st.session_state.section_progress[section_name]["status"] = "error"
                        continue
                
                try:
                    # Create section state
                    section_state: SectionState = {
                        "topic": st.session_state.topic,
                        "section": section,
                        "search_iterations": progress.get("iterations", 0),
                        "search_queries": progress.get("search_queries", []),
                        "source_str": progress.get("source_str", ""),
                        "report_sections_from_research": "",
                        "completed_sections": []
                    }
                    
                    # Verify search queries exist
                    if not section_state["search_queries"]:
                        st.error("No search queries available. Cannot proceed with search.")
                        st.session_state.section_progress[section_name]["status"] = "error"
                        continue
                        
                    st.write(f"Searching using {search_api_str}...")
                    try:
                        # Display search queries being used
                        st.write("Using these search queries:")
                        for i, q in enumerate(section_state["search_queries"], 1):
                            st.write(f"{i}. {q.search_query}")
                        
                        # Set a timeout for the search operation
                        result = asyncio.run(search_web(section_state, st.session_state.config))
                        
                        # Verify we have source content
                        source_str = result.get("source_str", "")
                        if not source_str:
                            raise ValueError("No search results were found")
                            
                        # Show search result summary
                        st.write(f"Found content from {len(progress.get('search_queries', []))} queries")
                        st.write(f"Retrieved {len(source_str.split())} words of content")
                        
                        # Update progress
                        st.session_state.section_progress[section_name]["source_str"] = source_str
                        st.session_state.section_progress[section_name]["search_iterations"] = result.get("search_iterations", 0)
                        st.session_state.section_progress[section_name]["status"] = "writing_section"
                        
                        st.success("Web search completed successfully")
                        time.sleep(1)
                        st.rerun()
                    except Exception as inner_e:
                        import traceback
                        error_details = traceback.format_exc()
                        st.error(f"Error during web search: {str(inner_e)}")
                        st.code(error_details, language="python")
                        
                        # Provide option to retry with different search api
                        if st.button(f"Try with {'DuckDuckGo' if 'TAVILY' in search_api_str.upper() else 'DuckDuckGo'} instead"):
                            # Switch to a different search API that doesn't require a key
                            new_config = st.session_state.config.copy()
                            new_config["configurable"]["search_api"] = "DUCKDUCKGO"
                            st.session_state.config = new_config
                            st.rerun()
                            
                        st.session_state.section_progress[section_name]["status"] = "error"
                except Exception as e:
                    import traceback
                    st.error(f"Error in web search process: {str(e)}")
                    st.code(traceback.format_exc(), language="python")
                    st.session_state.section_progress[section_name]["status"] = "error"
                
            elif status == "writing_section":
                st.info(f"Writing content for '{section_name}'")
                
                # Verify Google API key is set
                google_api_key = os.environ.get("GOOGLE_API_KEY", "")
                if not google_api_key:
                    st.error("Missing Google API Key - required for writing content")
                    st.session_state.section_progress[section_name]["status"] = "error"
                    continue
                
                try:
                    # Create section state
                    section_state: SectionState = {
                        "topic": st.session_state.topic,
                        "section": section,
                        "search_iterations": progress.get("iterations", 0),
                        "search_queries": progress.get("search_queries", []),
                        "source_str": progress.get("source_str", ""),
                        "report_sections_from_research": "",
                        "completed_sections": []
                    }
                    st.write(f"Writing section content for '{section_name}'...")
                    try:
                        st.write(f"Using model: {st.session_state.config.get('configurable', {}).get('writer_model', 'Not specified')}")
                        st.write(f"Working with {len(section_state['source_str'].split())} words of research content")
                        
                        # Check if content is too large and truncate if needed
                        source_content = section_state['source_str']
                        word_count = len(source_content.split())
                        if word_count > 6000:
                            st.warning(f"Content is very large ({word_count} words). Truncating to improve reliability.")
                            words = source_content.split()
                            source_content = " ".join(words[:6000])
                            section_state['source_str'] = source_content
                            st.write(f"Truncated to 6000 words")
                        
                        # Try normal write_section first with fallback
                        try:
                            # Write the section
                            result = write_section(section_state, st.session_state.config)
                        except Exception as write_err:
                            st.warning(f"Standard write process failed: {str(write_err)}. Attempting direct approach...")
                            # Fallback to direct content creation
                            result = create_direct_section_content(section_state, st.session_state.config)
                        
                        if result:
                            print("yes")
                            
                            # Extract update and completed section
                            update = result.update
                            print(update)
                            completed_sections = update.get("completed_sections", [])
                            print(completed_sections)

                            if not completed_sections:
                                raise ValueError("No completed sections found")

                            completed_section = completed_sections[0]  # First completed section
                            print(completed_section)

                            # Verify section content
                            if not completed_section.content or len(completed_section.content) < 50:
                                raise ValueError("Section content generation failed - content too short")

                            # Update section content
                            for i, s in enumerate(st.session_state.sections):
                                if s.name == completed_section.name:
                                    st.session_state.sections[i].content = completed_section.content

                            # Mark as completed
                            section_name = completed_section.name
                            st.session_state.section_progress[section_name]["completed"] = True
                            st.session_state.section_progress[section_name]["status"] = "completed"
                            st.session_state.completed_sections.append(completed_section)

                            st.success(f"Section '{section_name}' completed successfully!")

                            # Show a preview of the content
                            with st.expander("Section Content Preview", expanded=True):
                                st.markdown(completed_section.content)

                            time.sleep(1)
                            st.rerun()

                        else: 
                            print(result)
                            # Handle direct string content
                            st.warning("Got direct content without proper structure. Adapting...")
                            
                            # Create a completed section manually
                            from open_deep_research.state import Section
                            completed_section = Section(
                                name=section_name,
                                description=section.description,
                                research=True,
                                content=result
                            )
                            
                            # Update section and progress
                            for i, s in enumerate(st.session_state.sections):
                                if s.name == section_name:
                                    st.session_state.sections[i].content = result
                            
                            # Mark as completed
                            st.session_state.section_progress[section_name]["completed"] = True
                            st.session_state.section_progress[section_name]["status"] = "completed"
                            st.session_state.completed_sections.append(completed_section)
                            
                            st.success(f"Section '{section_name}' completed with adapted content!")
                            time.sleep(1)
                            st.rerun()

                    except Exception as inner_e:
                        import traceback
                        error_details = traceback.format_exc()
                        st.error(f"Error writing section content: {str(inner_e)}")
                        st.code(error_details, language="python")
                        st.session_state.section_progress[section_name]["status"] = "error"
                except Exception as e:
                    import traceback
                    st.error(f"Error in section writing process: {str(e)}")
                    st.code(traceback.format_exc(), language="python")
                    st.session_state.section_progress[section_name]["status"] = "error"
                
            elif status == "error":
                st.error(f"An error occurred while processing this section. Please try again or skip.")
                
                if st.button(f"Retry Section: {section_name}"):
                    st.session_state.section_progress[section_name]["status"] = "pending"
                    st.rerun()
                
                if st.button(f"Skip Section: {section_name}"):
                    st.session_state.section_progress[section_name]["completed"] = True
                    st.session_state.section_progress[section_name]["status"] = "skipped"
                    st.rerun()
        
        # Advance to the final report if all sections are completed
        if all_completed and completed_sections > 0:
            st.success("All research sections have been completed. Ready for the final report!")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Review & Download Report", type="primary"):
                    st.session_state.current_step = "final_report"
                    st.rerun()
        
    # Step 5: Final report generation and download
    elif st.session_state.current_step == "final_report":
        st.markdown("### Complete Research Report")
        st.markdown(f"**Topic: {st.session_state.topic}**")
        
        st.write("This is the complete report with all sections. You can review and download it.")
        
        # Generate final report content
        full_report = f"# {st.session_state.topic}\n\n"
        
        # Get the table of contents
        full_report += "## Table of Contents\n\n"
        for idx, section in enumerate(st.session_state.sections, 1):
            full_report += f"{idx}. [{section.name}](#{section.name.lower().replace(' ', '-')})\n"
        full_report += "\n\n"
        
        # Add each section content
        for section in st.session_state.sections:
            full_report += f"## {section.name}\n\n"
            if section.content:
                full_report += f"{section.content}\n\n"
            else:
                full_report += "*Content not available for this section.*\n\n"
        
        # Clean up the report formatting and remove any unexpected artifacts
        # Display the report with expanders for each section
        for idx, section in enumerate(st.session_state.sections, 1):
            with st.expander(f"Section {idx}: {section.name}", expanded=True):
                if section.content:
                    st.markdown(section.content)
                else:
                    st.warning("Content not available for this section.")
        
        # Download button for the complete report
        st.download_button(
            label="Download Full Report as Markdown",
            data=full_report,
            file_name=f"{st.session_state.topic.replace(' ', '_')}_report.md",
            mime="text/markdown",
        )
        
        # Also provide HTML download option
        html_report = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{st.session_state.topic}</title>
<style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 20px; }}
    h1 {{ color: #2c3e50; text-align: center; }}
    h2 {{ color: #3498db; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
    blockquote {{ background-color: #f9f9f9; border-left: 5px solid #ccc; margin: 1.5em 10px; padding: 0.5em 10px; }}
    code {{ background-color: #f8f8f8; border: 1px solid #ddd; border-radius: 3px; padding: 2px 5px; }}
    pre {{ background-color: #f8f8f8; border: 1px solid #ddd; border-radius: 3px; padding: 10px; overflow-x: auto; }}
    a {{ color: #3498db; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; }}
    tr:nth-child(even) {{ background-color: #f2f2f2; }}
    th {{ padding-top: 12px; padding-bottom: 12px; text-align: left; background-color: #3498db; color: white; }}
</style>
</head>
<body>
{markdown.markdown(full_report)}
</body>
</html>
"""
        
        st.download_button(
            label="Download Full Report as HTML",
            data=html_report,
            file_name=f"{st.session_state.topic.replace(' ', '_')}_report.html",
            mime="text/html",
        )
        
        # Add restart button to start a new report
        if st.button("Start New Research", type="primary"):
            # Reset session state except for configuration
            config = st.session_state.config  # Store current config
            for key in list(st.session_state.keys()):
                if key != "config":
                    del st.session_state[key]
            st.session_state.config = config  # Restore config
            st.session_state.current_step = "input"
            st.session_state.section_progress = {}
            st.session_state.completed_sections = []
            st.rerun()

if __name__ == "__main__":
    main()
