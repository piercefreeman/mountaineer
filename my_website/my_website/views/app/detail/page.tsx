import * as React from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();

  return (
    <div>
      <h1>Server</h1>
      <pre>{JSON.stringify(serverState, null, 2)}</pre>
      <a href={serverState.linkGenerator.homeController({})}>Go Home</a>
    </div>
  );
};

export default Page;
