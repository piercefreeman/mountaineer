import React from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();

  return (
    <div className="mx-auto max-w-3xl whitespace-pre-wrap rounded bg-red-50 p-4 text-red-700 ring-1 ring-inset ring-red-600/20">
      <div className="font-bold">{serverState.exception}</div>
      <div className="mt-4">{serverState.stack}</div>
    </div>
  );
};

export default Page;
