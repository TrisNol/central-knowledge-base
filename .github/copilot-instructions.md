# General instructions for GitHub Copilot

This repository is equipped with several custom agents and instructions targeted at the technology stack used in this repository. These instructions are designed to help GitHub Copilot generate code that is consistent with the project's coding standards and best practices.

Overall guidelines for specific types of files have been defined:
- [Agents instructions](./instructions/agents.instructions.md) - Provides guidance on how to define agents effectively.
- [Angular instructions](./instructions/angular.instructions.md) - Offers guidance on Angular best practices and coding standards.
- [Python instructions](./instructions/python.instructions.md) - Provides guidance on Python best practices and coding standards.
- [Workflow instructions](./instructions/workflows.instructions.md) - Offers guidance on GitHub Actions workflows and CI/CD best practices.

Always consider the other configuration files and hand off to the relevant agent when appropriate:
- [DevOps Expert Agent](./agents/devops-expert.agent.md) - Provides guidance on DevOps practices, CI/CD pipelines, and infrastructure as code.
- [Tech Lead Agent](./agents/tech-lead.agent.md) - Offers advice on software architecture, design patterns, and code reviews.
- [Product Owner Agent](./agents/product-owner.agent.md) - Assists with product management, user stories, and feature prioritization.

If there is no clear consensus on which agent to use, default to the Tech Lead Agent for code-related queries and the Product Owner Agent for product-related queries.

If the agents cannot come to a consensus, the Tech Lead Agent will have the final say on code-related matters, while the Product Owner Agent will have the final say on product-related matters.

Use the [i-have-adhd skill](./skills/i-have-adhd/SKILL.md) to shape output. This skill should be applied to all user messages, including coding tasks, debugging, explanations, planning, and casual conversation. The output should lead with concrete next actions, number multi-step work, externalize state across turns, suppress tangents, give specific time estimates, and make wins visible. Trigger this skill even on casual messages and even when the user did not explicitly ask for brevity.
