# Model-routed public conversation

Status: accepted.

The evidence requirement originally sent greetings and capability questions to knowledge
retrieval. An empty clarification also fell back to a fixed English message. The resulting
interaction was confusing even though the deployment used a real model.

The routing model now interprets social interaction, capability questions and business
follow-ups using a typed `conversation_kind`. Production routing does not match an allowlist
of user phrases. The server renders public capabilities from the current Profile, enabled
tools, user role and effective approval policy. Model-proposed prose on this route is ignored,
so misclassification cannot introduce unsupported business facts or promise an unauthorized
operation. Human-readable capability labels are packaged configuration, independent of
Profile names. Custom tools use their public description as a fallback.

Business questions still require evidence, and actions still pass schema, permission and
approval checks. For missing business arguments, the model writes a concrete clarification
in the user's language and can use the user's subsequent reply to complete that request.
Routing reasons are not displayed as clarification text. Assistant examples are not treated
as user-supplied action arguments.

Intent interpretation remains fallible. Tests cover typed routing, role/configuration changes,
untrusted model prose, replay and budgets; optional live acceptance covers varied phrasing,
clarification and continuation. Fake retains deterministic fixtures for offline CI. The v3
datasets keep historical labels intact and separately score public conversation and business
workflows; their combined score is not general model accuracy. Help presentation is bounded
configuration-backed text, not unrestricted social chat or unsupported factual answering.
