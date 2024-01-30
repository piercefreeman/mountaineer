## Sideeffects

Sideeffect: update the server data that has been pushed to the client. Sideeffects are also passthroughs, by definition.

Passthrough: expose an API to the client caller but don't update the server data.

We can't assume that any functions located in a controller could be called by the client, since there might be helper functions, auth functions, or the like. Instead we assume the user only wants to expose @sideeffect and @passthrough functions, leveraging @passthrough even for cases where no data gets returned.
