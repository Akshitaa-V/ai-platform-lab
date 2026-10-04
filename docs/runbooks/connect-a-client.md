# Connect a coding agent or LLM client to the platform

## MCP endpoint
The MCP server listens on `http://127.0.0.1:8000/mcp` using Streamable HTTP. It exposes four tools: list_models, ask_model, platform_status and search_runbooks.

## Coding agent CLIs
Register `http://127.0.0.1:8000/mcp` as an HTTP MCP server named `ai-platform` with the agent's MCP add command. Then ask the coding agent, for example, which models the platform serves or how to rotate the gateway key.

## MCP Inspector
Run `npx @modelcontextprotocol/inspector`, choose Streamable HTTP and enter the URL above to call each tool by hand.

## OpenAI-compatible clients
Any OpenAI SDK can call the gateway directly: set the base URL to `http://127.0.0.1:4000/v1` and the API key to the gateway master key, then use a model name from `aiplat models`.
