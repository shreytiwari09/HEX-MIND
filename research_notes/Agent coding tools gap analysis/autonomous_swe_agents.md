# Autonomous SWE agent platforms (OpenHands, Devin, GitHub Copilot coding agent, Cursor cloud agents) vs H.E.X Mind, as of Nov 2026

Research date: 2026-11-21. Primary sources (vendor docs, changelogs, blogs) preferred; third-party review sites flagged where used. Several vendor docs pages were only partly read (noted in Gaps).

## What features does each have (planning, multi-agent, sandbox, browser, testing, preview, terminal, git/PR, model choice, cost tracking, memory, integrations)?

### Takeaway
All four are cloud-first agents that work on an existing repo and hand back a branch/PR. In 2026 they all added parallel or sub-agents, per-task model choice, MCP, skills/custom agents and Slack-style triggers. Devin and Cursor also give the agent a full VM desktop with browser and computer use, and record screenshots and videos as proof. None uses a fixed team of role personas the way H.E.X does.

### Cited Findings

**OpenHands (open source, All Hands AI)**
- The 2026 product line is Agent Canvas (browser client and control center), OpenHands Cloud, the Software Agent SDK (Python), Agent Server (REST/WebSocket), Sandbox Server, Automation Server (scheduled and event-driven automations), Enterprise, and benchmark/evaluation infra. The old Docker local GUI (`openhands serve`) is deprecated, and the CLI is "no longer actively maintained." — [OpenHands docs](https://docs.openhands.dev/)
- Cloud adds hosted execution, integrations, collaboration, access controls, usage reporting and budget management. — [OpenHands docs](https://docs.openhands.dev/)
- Integrations include GitHub, GitLab and Bitbucket sign-in and repos, plus a Slack app. — [OpenHands Cloud docs](https://docs.openhands.dev/openhands/usage/cloud/openhands-cloud.md)
- Sub-agents: the SDK's `DelegateTool` uses built-in agent types (Explore, Bash) and user-defined agent types, each with its own skills and system-message suffix. — [SDK agent delegation guide](https://docs.openhands.dev/sdk/guides/agent-delegation.md)
- Browser: a Playwright Chromium browser in the sandbox. — [OpenHands paper, arXiv 2407.16741](https://arxiv.org/html/2407.16741v2)
- Models: model-agnostic routing across 100+ providers, reached through LiteLLM. — [OpenHands SDK paper, arXiv 2511.03690](https://arxiv.org/pdf/2511.03690v1)
- Releases v1.23.0 (Sep 2026) and v1.27.0 (Oct 2026) add DigitalOcean-hosted agents managed from Agent Canvas, plus an Enterprise Super Admin dashboard in beta. This comes from a third-party aggregator and is unverified. — [aipedia.wiki](https://aipedia.wiki/tools/openhands/)

**Devin (Cognition)**
- Each session runs on its own VM with a shell, an IDE editor and a browser. Devin tests the web apps it builds, and the user can step in through the Interactive Browser. It also offers a CLI with `/handoff` to cloud, an API, and Slack and Microsoft Teams integrations. Jira and Linear tickets are listed as task sources. — [Devin docs](https://docs.devin.ai/)
- Desktop computer use: since Feb 24 2026, new sessions get a full Linux desktop by default, so Devin can launch and test desktop apps. — [Cognition blog, "devin is getting a windows pc" / search summary](https://cognition.ai/blog/devin-is-getting-a-windows-pc); [Devin docs](https://docs.devin.ai/)
- Managed Devins (Mar 2026): a coordinator session splits a task, launches child sessions (each with its own prompt, skills, tags and ACU limits), monitors them, resolves conflicts and compiles the results. Available to all users. — [Cognition blog](https://cognition.com/blog/devin-can-now-manage-devins)
- From the Sep to Nov 2026 release notes:
  - Devin Bots (Nov 19): always-on Devins with their own identity, memory and permissions.
  - Playbooks are migrating to Skills (from Oct 23), and Knowledge can now be shared with groups.
  - MCP marketplace with per-tool permissions.
  - Preview that wakes sleeping sessions.
  - Recordings and screenshots at 2x resolution.
  - Budgets (Oct 30) and My Analytics.
  - GitLab `/devin` commands on merge requests, and merge trains.
  - Linear two-way sync for security findings, a Jira connection, and Slack and Teams thread modes.
  - Outposts (customer-hosted execution).
  - Source: [Devin release notes 2026](https://docs.devin.ai/release-notes/2026.md)
- Devin Desktop: a local IDE (the former Windsurf) with an Agent Command Center for parallel sub-sessions. Third-party source. — [DEV Community](https://dev.to/hassann/devin-vs-cursor-in-2026-windsurf-is-now-devin-desktop-ajo)
- Related paid products: Ask Devin, DeepWiki (codebase wiki) and Devin Review (PR review). — [Cognition pricing blog, Apr 14 2026](https://cognition.com/blog/new-self-serve-plans-for-devin)

**GitHub Copilot coding agent (now "Copilot in the cloud" / cloud agent)**
- It runs in two kinds of environment:
  - A GitHub Actions-based environment, which supports self-hosted runners, is limited to one repo and stops after 59 minutes.
  - A newer cloud sandbox, which can span several repos in one organization and follows firewall allowlists. It is available on paid plans from Oct 28 2026.
  - Source: [GitHub docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- It works on one branch at a time and opens one PR per task, on GitHub-hosted repos only. "Agent Merge" (Watch and fix) works on failing Actions runs and merge conflicts in a PR. — [GitHub docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- MCP: the GitHub MCP server is on by default. Cloud sandboxes add connectors and custom MCP servers. Custom agents, agent skills, custom instructions, dotfiles and hooks are supported. Tasks can be delegated from Slack and Microsoft Teams. — [GitHub docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- Feb 2026 additions:
  - A per-task model picker (or auto).
  - Self-review with Copilot code review before asking a human.
  - Built-in code scanning, secret scanning and dependency checks before the PR.
  - Custom agents in `.github/agents/`, shareable across an org.
  - Handoff between the CLI and the cloud ("Continue in Copilot CLI", `&`).
  - Source: [GitHub Blog, Feb 26 2026](https://github.blog/ai-and-ml/github-copilot/whats-new-with-github-copilot-coding-agent/)
- Partner custom agents for observability, IaC and security. — [GitHub Blog](https://github.blog/news-insights/product-news/your-stack-your-rules-introducing-custom-agents-in-github-copilot-for-observability-iac-and-security/)

**Cursor cloud agents (formerly background agents)**
- Each agent runs in an isolated cloud VM with cloned repos, dependencies, secrets and network access, and can work across several repos.
- Computer use: agents control a desktop and browser to test what they build, and produce screenshots, videos and logs as proof. Users can take over the agent's remote desktop and hand it back.
- Triggers: iOS, web, desktop, Slack, GitHub and Bitbucket comments, Linear, and the API.
- Models: a curated selection.
- MCP: stdio and HTTP transports, with OAuth.
- Environments: set up by the agent, from snapshots, or from a Dockerfile in `.cursor/environment.json`.
- Also: hooks, Tailscale private networking and self-hosted machines.
- Output is merge-ready PRs on a separate branch.
- Source for all of the above: [Cursor cloud agent docs](https://cursor.com/docs/cloud-agent)
- Changelog, Aug to Nov 2026:
  - Prebuilt environments ("builds"), with agents starting 3x faster.
  - Event-triggered agents that hold a goal over long sessions.
  - Cloud Agent Canvases, which are interactive canvases the agent builds (Oct 16).
  - Agent SDK (Oct 20): agents wake on GitHub, GitLab or Bitbucket PR, comment and CI events and on Slack messages, with a Linear/Jira triager template.
  - Origin App Marketplace (Oct 13).
  - Build Live Apps (Nov 5).
  - Voice chat with agents (Nov 6).
  - Environments for up to 300 repos, with the Environments API in beta.
  - Sources: [Cursor changelog](https://cursor.com/changelog); [Cursor changelog 08-19-26](https://cursor.com/changelog/08-19-26)

### Inferences
- Features all four now share: parallel or sub-agents, MCP, skill or custom-agent files, Slack-style triggers and a PR as the output. H.E.X's per-persona skills and MCP are at parity on mechanism, not ahead of these products.
- A recorded "proof of work" (screenshots and video from browser or computer use) is now standard in Devin and Cursor. This is the clearest testing and UX gap for H.E.X, which has no browser testing.
- None of the four documents a fixed team of role personas (PM, designer, QA, security…). Their sub-agents are generic workers or user-defined custom agents. None documents QA-authored acceptance tests as a gate before work is accepted, or a PM-led milestone and feature breakdown.

### Gaps
- OpenHands' skills/microagents system, MCP support and per-conversation cost display: the official overview pages read did not cover them.
- Copilot's Playwright MCP and screenshot verification: as of 2025, Copilot had Playwright MCP on by default, but this is unconfirmed in 2026 docs. Copilot's Jira and Linear integrations: searches found no 2026 GitHub source.
- Devin release notes were read only to character 100k of 267k, so earlier 2026 entries (for example the SWE models and Windsurf rename details) were not checked first-hand.
- Cursor docs don't describe user-facing subagents for cloud agents, only subagent lifecycle hooks.

## How does each deploy or host the apps it builds?

### Takeaway
Only Cursor ships first-party app hosting: since Nov 5 2026, cloud agents build, preview, security-check and publish live web apps, with Postgres and sign-in included. Devin offers in-session previews and lists "deployment" among its tasks but no documented hosting product. Copilot and OpenHands hand back PRs and leave deployment to the user's CI/CD.

### Cited Findings
- Cursor "Build Live Apps" (Nov 5 2026):
  - The agent scaffolds the app, provisions hosting, starts a Postgres database if needed and sets up sign-in behind Cursor SSO.
  - The user picks a domain and gets a live link. Publishing runs security checks (for example for exposed credentials), and "Nothing goes live until the checks pass and you explicitly publish the app."
  - Available on all paid plans with cloud agents enabled.
  - Source: [Cursor changelog](https://cursor.com/changelog)
- Cursor Apps, further details (third-party summary of Cursor's pages):
  - Cloud agents only, not local agents.
  - Starts from a new Cursor Origin repo or an existing GitHub repo; GitLab is "coming soon."
  - Each app runs in an isolated hosting account.
  - Sharing is invite-only, team-wide or public; public is off by default on Teams.
  - No published prices or quotas for hosting, database or traffic, and no named host provider or region.
  - Source: [DataStudios](https://www.datastudios.org/post/cursor-builds-hosts-live-web-apps-postgres-sign-in-cloud-agents)
- Devin:
  - Previews of HTML, PDF and SVG output open in a new tab, and a preview wakes a sleeping session. — [Devin release notes 2026](https://docs.devin.ai/release-notes/2026.md)
  - Docs list "deployment" among the tasks Devin handles end to end, with no dedicated hosting workflow found. — [search summary of Devin docs](https://docs.devin.ai/_llms/en/cloud.txt)
- Copilot coding agent: the output is a branch and PR on GitHub, and there's no documented hosting. — [GitHub docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
- OpenHands: the "DigitalOcean-hosted agents" in v1.27 host the agents, not the apps they build. This is a third-party source. — [aipedia.wiki](https://aipedia.wiki/tools/openhands/)

### Inferences
- Cursor's one-click publish targets non-developers building internal tools. H.E.X has no cloud deploy (planned as P9), so Cursor Apps is the closest reference design: build, check, explicit publish, managed database, gated sign-in.
- H.E.X's "explicit apply" rule matches Cursor's "nothing goes live until you explicitly publish."

### Gaps
- Devin's actual deploy mechanism in 2026 (older demos deployed to Netlify) could not be confirmed in current docs.
- Hosting pricing and limits for Cursor Apps are unpublished.

## What do they have that H.E.X lacks, and where is H.E.X ahead?

### Takeaway
H.E.X lags on cloud and remote execution, browser and computer-use verification with recordings, PR and issue-tracker integrations, live preview and hosting, and mobile and Slack triggers. It leads on a local-first desktop design that has no vendor lock-in or account. It also leads on any-provider per-persona models with measured Auto assignment, a structured PM, milestone and QA acceptance-test pipeline, detailed cost and latency observability, and a built-in evaluation harness.

### Cited Findings
- Competitor features H.E.X lacks:
  - Browser and computer use with screenshots and videos (Cursor, Devin). — [Cursor docs](https://cursor.com/docs/cloud-agent); [Devin docs](https://docs.devin.ai/)
  - Remote desktop takeover. — [Cursor docs](https://cursor.com/docs/cloud-agent)
  - App hosting with a database and auth. — [Cursor changelog](https://cursor.com/changelog)
  - PR workflow with self-review and security scans before the PR. — [GitHub Blog](https://github.blog/ai-and-ml/github-copilot/whats-new-with-github-copilot-coding-agent/)
  - Auto-fixing failing CI and merge conflicts. — [GitHub docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
  - Slack, Teams, Jira and Linear triggers. — [Devin release notes](https://docs.devin.ai/release-notes/2026.md)
  - Event and scheduled automations. — [OpenHands docs](https://docs.openhands.dev/); [Cursor changelog](https://cursor.com/changelog)
  - Persistent Knowledge and memory and always-on bots. — [Devin release notes](https://docs.devin.ai/release-notes/2026.md)
  - Budgets and team analytics. — [Devin release notes](https://docs.devin.ai/release-notes/2026.md); [OpenHands docs](https://docs.openhands.dev/)
  - Mobile and voice access. — [Cursor changelog](https://cursor.com/changelog)
- Model choice:
  - Copilot and Cursor offer a model picker limited to the vendor's curated list. — [GitHub Blog](https://github.blog/ai-and-ml/github-copilot/whats-new-with-github-copilot-coding-agent/); [Cursor docs](https://cursor.com/docs/cloud-agent)
  - Copilot "auto" mode exists. — [GitHub Blog](https://github.blog/ai-and-ml/github-copilot/whats-new-with-github-copilot-coding-agent/)
  - Only OpenHands is truly any-provider, through LiteLLM. — [arXiv 2511.03690](https://arxiv.org/pdf/2511.03690v1)
- Cost: Cursor charges cloud agents at the chosen model's API rate. — [Cursor docs](https://cursor.com/docs/cloud-agent)
- Evaluation: OpenHands ships public benchmark and evaluation infra. — [OpenHands docs](https://docs.openhands.dev/)

### Inferences
- **H.E.X is ahead in these areas:**
  - Role personas with per-persona models from any provider, plus an Auto assigner that measures account rate limits, speed and failures. Vendors offer only "auto" across their own list, and OpenHands offers a manual LiteLLM choice.
  - A QA-written acceptance-test gate and validators per feature.
  - Local Docker sandbox and git worktree, with nothing leaving the machine except model calls.
  - Per-run token, cost and latency traces.
  - A built-in evaluation harness. OpenHands is the only competitor with comparable eval infra.
- **H.E.X is behind in these areas** (biggest first):
  1. Browser and computer-use testing with recorded proof.
  2. A hosting or publish path.
  3. GitHub PR and CI integration.
  4. Live preview pane.
  5. Async triggers (Slack, Linear, Jira) and cloud execution while the laptop is closed.
- OpenHands is the closest open-source analogue and could be a reuse or benchmark reference. It's model-agnostic, Docker-sandboxed and has delegation, but it uses LiteLLM, which H.E.X's hard rules forbid.

### Gaps
- No independent head-to-head benchmarks for 2026 were collected in this pass.

## Pricing model and target user

### Takeaway
All four have moved to usage-based pricing on top of a subscription: Devin since Apr 2026, Copilot since Jun 1 2026 (AI credits) and Cursor (model API rates). OpenHands is free and open source, with paid Cloud and Enterprise tiers. Copilot, Devin and OpenHands target developers and engineering teams. Cursor's Apps feature now reaches toward non-developers building internal tools.

### Cited Findings
- Devin (from Apr 14 2026):
  - Free.
  - Pro: $20/mo.
  - Max: $200/mo.
  - Teams: usage-based with an $80/mo minimum, replacing the old $500/mo Team plan.
  - Enterprise: custom, still billed in ACUs.
  - Usage over quota is billed in dollars.
  - Deep Mode in Ask Devin, Devin Review and deeper DeepWiki generation are now paid.
  - Source: [Cognition blog](https://cognition.com/blog/new-self-serve-plans-for-devin)
  - On Oct 30 2026 the plan comparison was split into Devin Desktop and Devin Cloud. Third-party source. — [automationatlas.io](https://automationatlas.io/answers/devin-pricing-explained-2026/)
- GitHub Copilot:
  - All plans moved to usage-based AI credits ($0.01 each) on Jun 1 2026, replacing premium requests. — [GitHub Blog](https://github.blog/news-insights/enterprise-news/github-copilot-is-moving-to-usage-based-billing/)
  - Business: $19/seat with 1,900 credits. Enterprise: $39/seat with 3,900 credits. Max: $100/mo for heavy agent users. — [GitHub plans docs](https://docs.github.com/en/enterprise-cloud@latest/copilot/get-started/plans)
  - Pro: $10/mo. Pro+: $39/mo. — [GitHub Blog](https://github.blog/news-insights/enterprise-news/github-copilot-is-moving-to-usage-based-billing/); third-party figures differ.
  - Cloud agent compute draws on a separate monthly GitHub allowance, apart from AI credits. — [GitHub docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)
  - Older: in 2025 the agent used one premium request per session. — [GitHub changelog, Jul 2025](https://github.blog/changelog/2025-07-10-github-copilot-coding-agent-now-uses-one-premium-request-per-session/)
- Cursor (as of Nov 15 2026, third-party summary of Cursor's pages):
  - Free.
  - Plus: $8.
  - Premium: $30. Cloud agents and Apps start at this tier.
  - Super: $100.
  - Ultra: $200.
  - Teams: $30, $100 or $200 per seat.
  - Enterprise: custom.
  - Legacy Pro and Pro+ keep cloud agents.
  - Source: [DataStudios](https://www.datastudios.org/post/cursor-builds-hosts-live-web-apps-postgres-sign-in-cloud-agents)
  - Conflicts with an Aug 2026 guide listing Pro $20, Pro+ $60, Ultra $200 and Teams $40/$120. — [buildfastwithai](https://www.buildfastwithai.com/blogs/cursor-cloud-agents-development-environments-2026)
  - Cloud agents are billed at the model's API rate, and users set a spend limit on first use. — [Cursor docs](https://cursor.com/docs/cloud-agent)
- OpenHands:
  - Open source, self-hostable.
  - Cloud Individual tier is free, with about 10 conversations a day and LLM costs extra or at cost.
  - Teams is reported at $500/mo for up to 10 users.
  - Enterprise is custom.
  - All prices are from third-party sites that conflict with one another, and none is from the official pricing page. — [aiagentslist.io](https://www.aiagentslist.io/agents/openhands); [agentintellect.net](https://agentintellect.net/openhand/)

### Inferences
- Target users:
  - Copilot targets GitHub-centric engineering orgs.
  - Devin targets engineering teams working through backlogs (Slack, Jira, Linear tickets, migrations).
  - Cursor targets developers, plus internal-tool builders through Apps.
  - OpenHands targets developers and companies that want an open-source or self-hosted agent stack.
- H.E.X's pitch is "idea to software" by a persona team, with no account or vendor lock-in and bring-your-own keys, free models first. That places it nearer the non-technical idea-to-app segment than any of these four except Cursor Apps.

### Gaps
- The official OpenHands Cloud pricing page and the official Cursor pricing page were not fetched directly, so treat those price figures as provisional.
