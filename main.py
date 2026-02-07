from langchain_core.tools import tool
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from datetime import datetime
import requests

load_dotenv() 


@tool
def get_current_datetime() -> str:
    """Get the current date and time in YYYY-MM-DD HH:MM:SS format.
    
    Returns:
        Current date and time as a string.
    
    Example: "2026-02-07 14:30:45"
    """
    print("🔧 [DEBUG] get_current_datetime called")
    result = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🔧 [DEBUG] Returning: {result}")
    return result

@tool
def nh_events(start_date: str, end_date: str, page_number: int = 1) -> str:
    """Get events from the Visit NH API for a given date range.
    
    Args:
        start_date: Start date in ISO format YYYY-MM-DDTHH:MM:SS (e.g., "2026-02-07T00:00:00")
        end_date: End date in ISO format YYYY-MM-DDTHH:MM:SS (e.g., "2026-02-14T23:59:59")
        page_number: Page number for pagination, defaults to 1
    
    Returns:
        List of events with titles and dates, or error message.
    
    Example dates: "2026-02-01T00:00:00" for start, "2026-02-28T23:59:59" for end
    """
    print(f"🔧 [DEBUG] nh_events called with:")
    print(f"  - start_date: {start_date} (type: {type(start_date)})")
    print(f"  - end_date: {end_date} (type: {type(end_date)})")
    print(f"  - page_number: {page_number} (type: {type(page_number)})")
    
    url = "https://www.visitnh.gov/api/events/getitems"
    payload = {
        "pageNumber": page_number,
        "region": [],
        "city": [],
        "category": [],
        "startDate": start_date,
        "endDate": end_date
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            events = response.json().get("results", [])
            if not events:
                result = "No events found for the specified date range."
            else:
                result = "\n".join([f"- {event['title']} on {event['startDate']}" for event in events[:10]])
            print(f"🔧 [DEBUG] Found {len(events)} events")
            return result
        else:
            result = f"Error fetching events: {response.status_code}"
            print(f"🔧 [DEBUG] {result}")
            return result
    except Exception as e:
        print(f"🔧 [DEBUG] Exception: {str(e)}")
        return f"Error: {str(e)}"

model = init_chat_model(
    "llama3.2:3b",
    model_provider="ollama",
    temperature=0.5,
    timeout=30,
    max_tokens=1000
)

system_prompt = """You are a helpful assistant that can use tools to answer questions.

When working with dates:
1. First use get_current_datetime to find today's date
2. Calculate the date range needed (e.g., "this weekend" means Saturday and Sunday)
3. Format dates as YYYY-MM-DDTHH:MM:SS (e.g., "2026-02-07T00:00:00")
4. Then call nh_events with the correct start_date and end_date

Important: Always get the current date first before calculating date ranges."""

agent = create_agent(model=model, tools=[get_current_datetime, nh_events], system_prompt=system_prompt) 
response = agent.invoke(
    {"messages": [{"role": "user", "content": "what events are there this weekend?"}]}
)
print("\n" + "="*50)
print("RESPONSE:")
print(response['messages'][-1].content)
