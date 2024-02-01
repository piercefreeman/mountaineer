import * as React from "react";
import { useEffect } from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();

  // TODO: Refactor into global handler that is injected
  useEffect(() => {
    console.log("Page mounted2");
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-2xl">Server2</h1>
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
