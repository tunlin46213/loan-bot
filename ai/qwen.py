# ai/qwen.py
from openai import OpenAI

# Qwen uses OpenAI-compatible API
client = OpenAI(
    api_key="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",
    base_url="https://openrouter.ai/api/v1"
)

async def ask_qwen(user_question: str):
    
    system_prompt = """
    You are an expert Cambodia real estate 
    loan assistant for bankers.
    
    You know:
    - NBC regulations and Prakas
    - Cambodia property law  
    - Loan calculations (USD/KHR)
    - Hard Title vs Soft Title rules
    - Foreign buyer restrictions
    
    Reply in English or Khmer based on 
    what language the user writes in.
    """
    
    response = client.chat.completions.create(
        model="qwen/qwen-plus",  # or qwen3-max
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question}
        ]
    )
    
    return response.choices[0].message.content