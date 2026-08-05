# Scholens product principles

This document records durable product decisions. It describes the intended
user experience and should not prescribe implementation details that may
change as the system evolves.

## One conversational agent, contextualized by where the user is

All user-facing conversational experiences in Scholens should feel like the
same capable agent.

This includes conversations started from Home, Everything Ask, a project, or a
paper in the Reader. These surfaces should not become separate products with
different capabilities or independently maintained tool sets.

The differences between them come from context:

- the system guidance appropriate to the current experience;
- the information already in view and supplied to the conversation;
- sensible defaults inferred from where the conversation was started.

For example, a conversation opened from a paper should already understand that
paper. A conversation opened from a project should already understand the
project and naturally begin within that research scope. A broader conversation
should begin from the user's wider research library.

These starting points are defaults, not artificial capability boundaries. When
the user's request calls for a narrower or broader research scope, the same
agent should be able to adjust accordingly, provided the user is allowed to
access that information.

This symmetry is a deliberate product and maintenance principle:

- users should not need to learn which version of the agent can perform a
  particular task;
- the same interaction should behave consistently wherever it is initiated;
- new capabilities should strengthen the conversational product as a whole,
  rather than being implemented repeatedly for individual surfaces;
- product context should specialize the agent's behavior without fragmenting
  its underlying capabilities.

The interface should make the active context understandable and should reveal
when the agent intentionally works beyond that initial context. Tool activity,
sources, citations, progress, and errors should use a consistent interaction
language across all conversational surfaces.

Ordinary questions should receive ordinary answers. Research retrieval is a
capability the agent uses when evidence is needed, not a mandatory prelude to
every response. When tools are used, the product may disclose a concise,
inspectable activity history, but it must not expose model chain-of-thought,
raw tool arguments, provider heartbeats, or internal iteration mechanics.

That consistency includes the surrounding interface. New pages may have
different information architecture and density, but they should not invent an
independent visual or interaction dialect. Shared actions, context, progress,
feedback, and account behavior should remain recognizable so the product grows
as one system rather than a collection of separately themed tools.

Access control remains an invariant. Contextual flexibility must never allow an
agent to reach information the current user is not permitted to access.

Concrete event fields and tool schemas remain implementation contracts, but
the single-agent behavior and disclosure boundary above are durable product
requirements.
