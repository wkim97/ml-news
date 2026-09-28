# ml-news

A daily, **hot-only** AI/ML news email for researchers. It collects from lab blogs, Hugging Face,
Hacker News, Reddit, GitHub trending, and newsletters. Then Claude drops the noise and writes each item as
**what happened → why it matters → links**, grouped into **Vision / NLP / Robotics / General ML**, and the email lands in your inbox every morning.

```
💬 NLP
* [릴리스] Naive-N0.5-Flash (309B-A15.5B)
  MIT 라이선스 오픈 MoE, 1M 컨텍스트, full attention 없이 SWA+DSA 하이브리드, SWE-bench Pro 73.6
  → full attention 없이 1M 컨텍스트 달성한 오픈 레시피, 장문맥 아키텍처 연구 참고용
  Naive research · HF · Reddit
```

## Sources
| Type | Sources |
|---|---|
| Labs (official) | OpenAI, Anthropic*, Google DeepMind, Google Research, Meta AI*, Qwen, Hugging Face blog |
| Community signal | Hacker News (≥100 pts), r/LocalLLaMA, r/MachineLearning, HF trending models, HF daily papers, GitHub trending |
| Social | Bluesky (free public API), X (optional, official pay-per-use API, ~$15/mo at the default cap) |
| Robotics | The Robot Report, IEEE Spectrum Robotics |
| Newsletters | Latent Space + AINews (daily X/Reddit/Discord recap), Simon Willison, Import AI, Ahead of AI, The Decoder |
| Catch-all | Claude runs a few web searches (per field, including x.com / LinkedIn) for major releases the feeds missed |

\* community-maintained RSS mirrors. All sources are configurable in `config.toml`.

## Setup
Requirements: Linux with cron, Python ≥ 3.11 (no pip packages), [Claude Code](https://claude.com/claude-code) CLI logged in (`claude` → `/login`), and a Gmail account.

```bash
git clone https://github.com/wkim97/ml-news && cd ml-news
cp .env.example .env && chmod 600 .env
#   fill in GMAIL_ADDRESS, GMAIL_APP_PASSWORD (https://myaccount.google.com/apppasswords), DIGEST_TO
#   optional: X_BEARER_TOKEN to include X posts (paid API)
#   edit config.toml → [profile] to describe your interests and language

python3 -m mlnews --dry-run     # preview (no email)
python3 -m mlnews --force       # send one now
bash scripts/install_cron.sh 08:40   # daily at 08:40 local time
```

Logs go to `logs/`, and per-run artifacts go to `runs/<date>/`. See [CLAUDE.md](CLAUDE.md) for internals.

LinkedIn isn't collected directly because it has no public read API and its terms prohibit scraping. The curator's web search covers it instead.
