import React from "react";
import { useServer } from "./_server";

const Page = () => {
  const serverState = useServer();

  return (
    <div className="p-6">
      <h1 className="text-2xl">Server72</h1>
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
