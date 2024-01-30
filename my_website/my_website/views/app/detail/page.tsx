import * as React from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();

  return (
    <div>
      <h1>Server</h1>
      <pre>{JSON.stringify(serverState, null, 2)}</pre>
    </div>
  );
};

export default Page;
