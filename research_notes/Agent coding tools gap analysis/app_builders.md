# AI app builders for non-technical users (Replit Agent, Bolt.new, Lovable, v0), compared with H.E.X Mind

Researched 2026-11-21 from official docs, pricing pages and changelogs. Doc pages are undated unless noted, so read them as "current as of Nov 2026". Pricing pages carry no effective date.

## Onboarding and UX: live preview, visual edits, screenshot/Figma input, templates, undo/checkpoints, chat-first flows

### Takeaway
All four are browser-based and chat-first. Each has a live preview next to the chat, point-and-click visual editing, Figma import, image or URL input, and version restore. Lovable and Replit add plan modes. Replit Agent 4 (March 2026) adds parallel tasks and a design canvas. H.E.X has none of the visual, preview or import features.

### Cited Findings
**Lovable**
- Preview toolbar: select elements, edit text inline, annotate and comment directly on the preview. The preview can be checked at different screen sizes and shared by link. — [docs.lovable.dev/features/preview-toolbar](https://docs.lovable.dev/features/preview-toolbar.md); [preview](https://docs.lovable.dev/features/projects/preview.md)
- Figma import through the Figma plugin, Figma MCP or a .fig file, including tokens and components. — [docs.lovable.dev/integrations/figma](https://docs.lovable.dev/integrations/figma.md)
- File attachments in chat, "Build with URL" (reference images and web pages), and import of a website you own from its URL. — [chat](https://docs.lovable.dev/features/projects/chat.md); [build-with-url](https://docs.lovable.dev/integrations/build-with-url.md); [import-website](https://docs.lovable.dev/features/projects/import-website.md)
- Templates: design templates that copy a full project, plus reusable design systems. Design templates are listed as a Business-plan feature. — [design-templates](https://docs.lovable.dev/features/business/design-templates.md); [design-systems](https://docs.lovable.dev/features/design-systems.md); [lovable.dev/pricing](https://lovable.dev/pricing)
- Version history (preview, revert, bookmark stable states), and "drafts" that test changes, including database changes, in a copy before you accept them. — [history](https://docs.lovable.dev/features/projects/history.md); [drafts](https://docs.lovable.dev/features/drafts.md)
- Plan mode writes a plan you approve before code changes; it costs 1 credit plus any subagent research. — [plan-mode](https://docs.lovable.dev/features/plan-mode.md); [agent-mode](https://docs.lovable.dev/features/agent-mode.md)
- Build mode "implement[s] and verif[ies] changes". Its tools include browser testing, frontend tests, edge-function verification, web search and fetch, image and video generation, and console, network and log inspection. Most verification runs only on request. A message can run up to 10 hours, with credit check-ins at 20 credits by default. — [agent-mode](https://docs.lovable.dev/features/agent-mode.md)
- Two-way GitHub sync, plus GitLab and Bitbucket. — [github](https://docs.lovable.dev/integrations/github.md); [git-sync-overview](https://docs.lovable.dev/integrations/git-sync-overview.md)

**Bolt.new**
- A project can start from a blank prompt, uploaded files, a Figma or Google Stitch design, or a team template. — [start-project](https://support.bolt.new/building/start-project.md); [figma](https://support.bolt.new/integrations/figma.md); [team-templates](https://support.bolt.new/teams/team-templates.md)
- Visual edits with a Select tool in the preview, preview controls including theme changes, and a Code view with a terminal. — [visual-edits](https://support.bolt.new/building/visual-edits.md); [preview-controls](https://support.bolt.new/building/preview-controls.md); [code-view](https://support.bolt.new/building/code-view.md)
- Image upload, AI image editing and image generation. — [images](https://support.bolt.new/building/images.md)
- Restore, automatic backups, version history and GitHub sync. — [rollback-backup](https://support.bolt.new/managing-projects/rollback-backup.md); [git](https://support.bolt.new/integrations/git.md)
- Agents: "Standard" (balanced, the only agent on the free plan) and "Max" (more reasoning, paid). "Forge" uses open-source models. The models are not named, and Bolt "selects the model behind the scenes". — [agents](https://support.bolt.new/building/agents.md); [bolt-forge](https://support.bolt.new/account/bolt-forge.md)
- MCP connectors give the agent external tools. — [mcp](https://support.bolt.new/integrations/mcp.md)

**Replit Agent**
- Agent 4 launched on 2026-03-13 with parallel tasks, a Design Canvas for mockups before code, mobile apps, plan mode, multiplayer collaboration, and connectors (BigQuery, Linear, Slack, Notion). — [Replit changelog 2026-03-13](https://docs.replit.com/updates/2026/03/13/changelog)
- The task system splits work into reviewable tasks that run in the background. — [task-system](https://docs.replit.com/core-concepts/agent/task-system.md)
- Replit Design has an infinite canvas, a visual editor (text, colors, layout, images without code) and Figma frame import. — [visual-editor](https://docs.replit.com/design/visual-editor.md); [canvas](https://docs.replit.com/design/canvas.md); [Figma import](https://docs.replit.com/design/import-figma-designs-into-replit-design.md)
- Agent modes: Free (uses "intelligent model routing", with an allowance that refreshes every 5 hours on Core and Pro), Power and Max. Replit warns before a request moves to a paid mode. — [agent-modes](https://docs.replit.com/chat/agent-modes.md)
- Checkpoints are billed and used for rollback. The Pro plan adds database rollback up to 28 days. — [ai-billing](https://docs.replit.com/billing/ai-billing.md); [replit.com/pricing](https://replit.com/pricing)
- Native iOS and Android apps through Expo: Expo Go preview, TestFlight and App Store submission. — [mobile-first-app](https://docs.replit.com/build/mobile-first-app.md); [mobile-publish-ios](https://docs.replit.com/build/mobile-publish-ios.md)
- A third-party source says Agent 4 ran on Claude Opus 4.7 from April 2026 and that a Monitoring Agent was added in Oct 2026. Not checked in Replit's own docs. — [search summary citing docs.replit.com changelogs](https://docs.replit.com/updates/2026/04/17/changelog)

**v0 (Vercel)**
- Design Mode: select an element in the live preview and edit typography, colors, spacing, borders, shadows and text, or describe structural changes in words. A screenshot of the selected element is attached to the instruction automatically. Each Apply creates a new chat version you can revert. — [v0.app/docs/design-mode](https://v0.app/docs/design-mode)
- Since the 2026-02-04 update, previews run the full app: server code, API routes, database connections and environment variables. — [v0 docs (search summary)](https://v0.app/docs/full-stack-apps)
- Agentic features: live web search, browser use (v0 opens and tests the apps it builds and shares screenshots), automatic error fixing, terminal commands (unit tests, Vercel and GitHub CLIs), three autonomy modes (Ask, Auto, Full), and MCP servers. "Every action runs in an isolated sandbox." — [agentic-features](https://v0.app/docs/agentic-features)
- Models: Vercel AI Gateway by default, or fal, Deep Infra, Grok, or your own provider keys. A ChatGPT plan can be used for eligible responses. — [v0.app/docs/llms.txt index (ai-models, chatgpt pages)](https://v0.app/docs/llms.txt)
- Design-system skills, a Figma doc and a community gallery at v0.app/community. — [llms.txt index](https://v0.app/docs/llms.txt)

### Inferences
- An image, screenshot or Figma frame as input is standard on all four. H.E.X's lack of image input is the most visible onboarding gap for a non-technical user.
- Lovable drafts and v0's "Apply creates a version" are close to H.E.X's apply-on-approval model, but they act on hosted copies, not on the user's local files.
- Replit Agent 4's parallel tasks with approval before merging look like H.E.X's milestone and feature split, but presented as a kanban rather than personas.

### Gaps
- Replit's docs pages fetched do not describe "App Testing" (the agent testing in a browser). Whether it is still a separate feature in Agent 4 is not confirmed.
- I found no first-party page naming the models used by Lovable, Bolt or Replit Agent 4.
- Bolt runs in-browser on StackBlitz WebContainers (from earlier knowledge). I did not fetch a 2026 page confirming that code still runs there.

## Built-in backend services: database, auth, storage, payments

### Takeaway
Lovable (Lovable Cloud, built on Supabase) and Bolt (Bolt Cloud database, Supabase-based) bundle a database, auth, storage, server functions and secrets with no extra accounts. Replit has its own PostgreSQL, Replit Auth or Clerk, and App Storage. v0 adds Neon, Supabase, Upstash or Blob through the Vercel Marketplace. All four have Stripe paths. H.E.X has none.

### Cited Findings
- **Lovable Cloud** is on by default: database, auth (email, phone, social, SSO), storage, realtime, edge functions, secrets, scheduled jobs, logs, daily backups and AI. It "utilizes Supabase's open-source foundation". The region (Americas, Europe or Asia Pacific) is locked once enabled. Database actions can be set to always allow, ask each time or never allow. Moving from Supabase to Cloud is not supported. — [cloud](https://docs.lovable.dev/features/cloud.md); [authentication](https://docs.lovable.dev/features/authentication.md); [database-backups](https://docs.lovable.dev/features/database-backups.md)
- **Lovable** payments: built-in Paddle or Stripe, or your own Stripe account. Also Shopify storefronts and a built-in AI connector for app features. Security scans cover API keys, database access (RLS) and dependencies. — [payments](https://docs.lovable.dev/features/payments.md); [stripe](https://docs.lovable.dev/integrations/stripe.md); [shopify](https://docs.lovable.dev/integrations/shopify.md); [security](https://docs.lovable.dev/features/security.md)
- **Bolt Cloud database:** Bolt creates one automatically when needed, with no limit on databases. It includes tables, auth (email, Google), storage buckets, server functions, secrets, logs and an RLS security scan. You can claim it into your own Supabase account, or use Supabase instead (Pro and Teams). Published projects' databases are not paused. — [database](https://support.bolt.new/bolt-cloud/database.md); [advanced](https://support.bolt.new/bolt-cloud/database/advanced.md); [supabase](https://support.bolt.new/integrations/supabase.md); [cloud/database](https://support.bolt.new/cloud/database)
- **Bolt** Stripe integration (API keys, product import, webhooks, test payments) and a project security audit that Bolt can fix. — [stripe](https://support.bolt.new/integrations/stripe.md); [security](https://support.bolt.new/building/security.md)
- **Replit:** a built-in database (PostgreSQL usage billing), Replit Auth or Clerk Auth, App Storage (object storage), a Stripe connector or your own keys, and connectors that activate from prompts. — [add-database](https://docs.replit.com/build/add-database.md); [auth](https://docs.replit.com/learn/projects-and-artifacts/auth.md); [object-storage-billing](https://docs.replit.com/billing/object-storage-billing.md); [stripe](https://docs.replit.com/use-cases/accept-payments-with-stripe.md); [connectors](https://docs.replit.com/chat/connectors.md)
- **v0:** one-click Neon (Postgres), Supabase (Postgres, auth, realtime), Upstash Redis and Vercel Blob, through Project → Integrations or by asking in chat. Each opens the Marketplace with click-through terms. Stripe and others come as Marketplace integrations that also expose tools to the agent. — [databases](https://v0.app/docs/databases); [agentic-features](https://v0.app/docs/agentic-features)

### Inferences
- Lovable and Bolt hide the backend entirely (no third-party account), which is the best fit for non-technical users. v0 relies on Vercel Marketplace partners, and Replit is in between.
- H.E.X can produce code that uses Supabase or Stripe, but the user has to set up accounts and keys alone. That is a big hurdle for this audience.

### Gaps
- Exact database quotas and prices per plan (Lovable "Run credits", Bolt's database capacity, Replit PostgreSQL rates) were not listed on the pages fetched.

## Deployment and hosting: how each publishes, domains, pricing, where code runs

### Takeaway
All four publish in one click to their own cloud, with a free subdomain (lovable.app, Bolt-hosted, .replit.app, vercel.app). Custom domains need a paid plan, and three of them sell domains inside the product. Code is built and run in the vendor's cloud: Replit containers, Vercel sandboxes, Lovable and Bolt hosting. All except Replit sell entry plans at about $20 to $30 a month.

### Cited Findings
- **Lovable:** publish to a live URL, push updates, take offline. Hosting has HTTPS, global delivery and auto-scaling. Visitor access controls. Custom domains can be bought, connected or transferred. Enterprise can publish a whole workspace under one domain. Export to your own hosting or Supabase is documented. — [publish](https://docs.lovable.dev/features/publish.md); [hosting](https://docs.lovable.dev/features/hosting.md); [custom-domain](https://docs.lovable.dev/features/custom-domain.md); [external-deployment](https://docs.lovable.dev/tips-tricks/external-deployment-hosting.md)
- **Lovable pricing (undated page):** Free $0 (5 daily credits up to 30 a month, 5 lovable.app domains, no custom domain, badge shown). Pro $25 (100 monthly credits plus daily grants, custom domains, badge removed). Business $50 (SSO, workspace-only publishing, security center, design templates). Enterprise custom. Every plan gets 20 Cloud credits a month. — [lovable.dev/pricing](https://lovable.dev/pricing); custom domains need a paid plan per [FAQ](https://lovable.dev/faq/domains/plans)
- **Bolt Cloud hosting:** Free tier is 10 GB a month and 333,333 requests, then stops serving, with a "Made in Bolt" badge. Pro tier is 30 GB and 1M requests, then pay-as-you-go up to a cap, and comes with every paid plan. Includes visit analytics, domain purchase or connection, DNS records, aliases and SSL. Netlify is an alternative publish target. — [hosting plans](https://support.bolt.new/bolt-cloud/hosting/plans.md); [analytics](https://support.bolt.new/bolt-cloud/hosting/analytics.md); [domains](https://support.bolt.new/bolt-cloud/domains.md); [netlify](https://support.bolt.new/integrations/netlify.md)
- **Bolt pricing:** Free $0 (1M tokens a month, 300K daily cap). Pro $25 a month (10M+ tokens with rollover, custom domain, badge removed). Teams $30 per member. Enterprise custom. — [bolt.new/pricing](https://bolt.new/pricing)
- **Replit publishing:** Preview becomes a separate production deployment. Types: Autoscale, Reserved VM, Static, Scheduled. Free .replit.app subdomain (renamable), custom domains, domain purchase. Access can be public, password, workspace-only or invite-only. Optional deep security scan, and a setting can "Block publishing of critical vulnerabilities". Monitoring pane (requests, status codes, latency, CPU and memory) and Growth pane (visitors, SEO). Starter includes 1 published app that expires after 30 days. — [publish-your-app](https://docs.replit.com/build/publish-your-app.md); [add-custom-domain](https://docs.replit.com/build/add-custom-domain.md); [domain-purchasing](https://docs.replit.com/build/domain-purchasing.md)
- **Replit pricing:** Core $20 a month ($18 yearly) with $20 of credits. Pro $100 a month with $100 of credits plus $100 for top models, 15 collaborators and 28-day database rollback. Enterprise adds SSO, SCIM, single-tenant and private networking. Publishing is billed by usage. — [replit.com/pricing](https://replit.com/pricing); [deployment-pricing](https://docs.replit.com/billing/deployment-pricing.md)
- **v0:** "v0 deploys projects to Vercel", with a vercel.app production URL, preview deployments per branch, custom domains managed in Vercel, and visibility controlled by Vercel deployment protection. GitHub projects publish by PR and merge, and branch protection applies. There is a "Fix with v0" button for failed deploys. — [v0.app/docs/deployments](https://v0.app/docs/deployments)
- **v0 pricing:** Free $0 (7 messages a day, deploy to Vercel, Design Mode, GitHub sync). Plus $30 per user ($30 monthly plus $2 daily credits, all models). Business $100 per user (training opt-out). Enterprise custom (SAML SSO, no training). — [v0.app/pricing](https://v0.app/pricing)

### Inferences
- "Shipped and hosted" takes one button and needs no infrastructure knowledge on all four. H.E.X stops at a localhost link, so the user still has to learn hosting. This is the biggest gap for non-technical users, and it matches H.E.X's planned P9.
- Replit's "block publishing of critical vulnerabilities" gate and v0's deploy-by-PR are close to H.E.X's QA and security personas plus approval gates. They are a useful model for H.E.X's future deploy step.

### Gaps
- Bolt's hosting page does not say which infrastructure runs published sites (it may be Netlify-backed; not confirmed).
- Exact Replit deployment unit prices were not retrieved.

## What they have that H.E.X lacks, and where H.E.X is ahead

### Takeaway
They lead on everything that makes the path from idea to URL short for a non-coder: hosting, domains, a bundled backend, payments, a live preview, visual edits, image and Figma input, templates and mobile apps. H.E.X's possible lead is control and verifiability: any provider and model per persona, local and private execution, Docker-sandboxed QA acceptance tests, apply only on approval in git worktrees, and full cost and token traces. Note that v0 and Replit now also run code in sandboxes and test in a browser, so "sandboxed verification" alone no longer sets H.E.X apart.

### Cited Findings
- Model choice in the competitors is limited and vendor-picked. Bolt "selects the model behind the scenes" ([agents](https://support.bolt.new/building/agents.md)). Replit Free mode routes models automatically, and Power and Max are tiers, not named models ([agent-modes](https://docs.replit.com/chat/agent-modes.md)). v0 is the exception: AI Gateway or your own provider keys ([llms.txt index](https://v0.app/docs/llms.txt)).
- Cost visibility in the competitors is credit-based. Lovable gives "no upfront estimate" and shows only the credits used per request ([agent-mode](https://docs.lovable.dev/features/agent-mode.md)).
- Training and privacy are tied to plan: v0's training opt-out is on by default only on Business ($100 per user) and above ([v0.app/pricing](https://v0.app/pricing)). All four are cloud-hosted builders.
- Competitors also verify: v0 runs commands and browser tests in an isolated sandbox ([agentic-features](https://v0.app/docs/agentic-features)). Lovable has browser and frontend tests, mostly run on request ([agent-mode](https://docs.lovable.dev/features/agent-mode.md)). Bolt, Lovable and Replit have security scans ([Bolt security](https://support.bolt.new/building/security.md); [Lovable security](https://docs.lovable.dev/features/security.md); [Replit publish](https://docs.replit.com/build/publish-your-app.md)).

### Inferences
- **H.E.X lacks:** cloud publish and domains; a bundled database, auth, storage and payments; an in-app live preview; visual and point-and-click edits; image, screenshot and Figma input; templates; one-click GitHub sync; mobile app builds; checkpoint restore in the UI (H.E.X has git, but nothing a non-technical user can click to undo); multiplayer collaboration.
- **H.E.X is ahead on:** per-persona model choice from any provider with an Auto assigner (only v0 allows your own keys); local-first execution with the user's files untouched until approval; explicit QA acceptance tests per feature, rather than tests run on request; a visible role team (PM, security, reviewer) instead of a single agent; trace-level observability (tokens, cost, latency) instead of opaque credits; no per-seat platform fee beyond the user's own API costs.
- To compete for non-technical users, the cheapest high-impact additions would be a preview pane, image input, a deploy target (for example Vercel or Netlify CLI from the sandbox), and a bundled backend option (for example a Supabase connector). That ranking is my own inference.

### Gaps
- No independent 2026 benchmarks comparing success rates or app quality across the four were gathered.
