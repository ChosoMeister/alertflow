# Sentinel-AI-Core Walkthrough

## 2026-02-08 18:34 (Asia/Baku)
Type: Walkthrough Update

### Current State
Project is in planning phase. Implementation plan created based on analysis of two source projects:
1. `/Users/mustafa/Documents/Git/Gitlab-Orchidpharmed/Sentinel-AICore` - Existing implementation with basic routing rules
2. `/Users/mustafa/Documents/Git/Gitlab-Orchidpharmed/sentinel-core` - Original project with regex-based parsing

### Key Findings from Source Analysis

#### Sentinel-AICore (Current)
- FastAPI backend with Redis storage
- Basic routing rules (exact/domain pattern matching)
- Next.js UI with shadcn components
- Alert processor with Ollama integration

#### sentinel-core (Legacy)
- Streamlit dashboard
- OpenAI + Ollama (fallback) AI
- Regex-based rule matching
- Dynamic rule learning

### Planned Improvements
1. Enhanced glob pattern matching
2. Test Email with FROM field and routing preview
3. Test-match API endpoint
4. Improved rule schema (enabled, match_field, notes)
