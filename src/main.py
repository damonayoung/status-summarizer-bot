import os
import datetime
from dotenv import load_dotenv
from openai import OpenAI

# Load your .env file (contains OPENAI_API_KEY and OPENAI_MODEL)
load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
API_KEY = os.getenv("OPENAI_API_KEY")

if not API_KEY:
    raise EnvironmentError("❌ Missing OPENAI_API_KEY — set it in your .env file.")

client = OpenAI(api_key=API_KEY)

INPUT_FILE = "sample_data/meeting_notes.txt"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def summarize(text: str) -> str:
    """Call OpenAI to summarize meeting or project notes."""
    prompt = f"""You are a Technical Program Manager AI assistant.
Summarize the following notes into a brief weekly report with:
- Highlights
- Risks & Mitigations
- Next Steps
- Stakeholder Pulse (Eng, Product, Ops)

Notes:
{text}
"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You create crisp TPM executive summaries."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def write_markdown(summary: str) -> str:
    today = datetime.date.today().strftime("%Y-%m-%d")
    filename = f"weekly_summary_{today}.md"
    out_path = os.path.join(OUTPUT_DIR, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Weekly Summary ({today})\n\n{summary}\n")
    return out_path


def main():
    notes = read_text(INPUT_FILE)
    summary = summarize(notes)
    path = write_markdown(summary)
    print(f"✅ Wrote summary to {path}")


if __name__ == "__main__":
    main()
