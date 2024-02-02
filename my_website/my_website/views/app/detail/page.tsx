import * as React from "react";
import { useEffect } from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();

  // TODO: Refactor into global handler that is injected
  useEffect(() => {
    console.log("Trying to connect to webservice hi15...");
    const ws = new WebSocket("ws://127.0.0.1:5015/build-events");
    ws.onmessage = (event) => {
      console.log("EVENT", event);
      // Refresh the current page
      window.location.reload();
    };
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-2xl">Server30</h1>
      <pre>{JSON.stringify(serverState, null, 2)}</pre>
      <a
        className="font-medium text-blue-500"
        href={serverState.linkGenerator.homeController({})}
      >
        Go Home
      </a>
    </div>
  );
};

export default Page;
