# RefundGuard

A financial stress test for AI agents that can move money.

Built at Test Flight, the Glasswing Ventures hackathon, September 26 and 27, 2026.

Team: Name (@github), Name (@github), Name (@github)


## The problem

Companies are starting to give AI agents real authority: issue refunds, add credits, cancel orders, and make decisions that affect money. Before shipping one, the practical question is: how much can this agent cost the business when a customer actively tries to manipulate it?

RefundGuard stress tests a money-moving agent before production. It runs adversarial AI customers that adapt during conversations and attempt duplicate refunds, fake approvals, prompt injection, inflated claims, and accessing someone else's order.

An agent can create risk without ever calling a payment tool — it can promise an unauthorized refund, misstate policy, or expose customer data. So RefundGuard uses two independent evaluation layers: deterministic policy enforcement that audits every tool call and dollar moved, and an LLM judge that evaluates language-level failures that code alone can't easily capture. Because an LLM judge can hallucinate too, every finding must provide verbatim evidence from the conversation, verified programmatically before being accepted.

RefundGuard also runs honest customers as a control group, because an agent that refuses every request has zero financial loss and zero business value — that's not success, it's just cowardice.

The end result is a CI release gate for money-moving agents: if an agent leaks money, makes unauthorized promises, exposes customer data, or fails legitimate customers, the build fails before deployment.


## Who pays

The buyer, the budget it comes out of, and why they would sign.


## How it works

- Node.js
- Multi-model agent orchestration
- Server-Sent Events
- Deterministic policy evaluation
- Automated adversarial test generation
- 14 unit tests
- GitHub Actions

One recorded stress test ran 195 real model calls across ~640K tokens.


## What's real and what's mocked

Be specific. Which integrations are live, which data is synthetic, what would break at real scale.


## Running it

```bash
cp .env.example .env   # put your keys in .env, it never gets committed
# install and run steps here
```


## Brought in from before the weekend

None. (If you brought existing code, say what it was here. Before any new work, commit that code as it was before the weekend, with the message "prior work". Open-source libraries, public models and APIs don't need listing.)