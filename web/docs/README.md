# Scholens Web Engineering Handbook

This directory is the operating contract for the replacement frontend. Its
purpose is to keep the codebase easy to change as product routes are added.

## Source-of-truth order

When two sources disagree, use this order:

1. Executable contracts: TypeScript, generated schemas, tests, and CI.
2. Architecture decisions in `docs/decisions/`.
3. The engineering guides in this directory.
4. Figma annotations and product notes.

Figma remains the source for layout intent, visual hierarchy, interaction
states, and design acceptance. The repository is the source for token values,
runtime behavior, accessibility, data contracts, and component APIs.

## Guides

| Guide                                                       | Read it when                                                         |
| ----------------------------------------------------------- | -------------------------------------------------------------------- |
| [Architecture](./architecture.md)                           | Adding a route, feature slice, provider, shared state, or dependency |
| [Component development](./component-development.md)         | Creating or importing a component                                    |
| [Design tokens](./design-tokens.md)                         | Changing color, spacing, radius, theme, or Figma variables           |
| [Internationalization](./internationalization.md)           | Adding UI copy, locale behavior, formatting, or another language     |
| [Authentication foundation](./authentication-foundation.md) | Building auth UI, session behavior, responsive auth layout, or mocks |
| [API development](./api-development.md)                     | Changing a backend contract or adding a request/query                |
| [Testing](./testing.md)                                     | Choosing test scope or adding a network/interaction state            |
| [New feature checklist](./new-feature-checklist.md)         | Starting and finishing every product feature                         |
| [Architecture decisions](./decisions/README.md)             | Deliberately changing a rule in this handbook                        |

## Maintenance rule

Documentation changes ship with the code that invalidates them. Do not create
parallel guides in feature folders. Feature-local README files may explain
domain behavior, but architecture, component, token, API, and testing rules
remain centralized here.
