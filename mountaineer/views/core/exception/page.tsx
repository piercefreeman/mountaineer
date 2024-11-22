import React from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();
  const timestamp = new Date().toISOString();

  return (
    <div className="mx-20 space-y-6 rounded-lg bg-zinc-50 p-8 shadow-lg ring-1 ring-zinc-200">
      <div className="space-y-2">
        <div className="text-sm text-zinc-500 font-mono">
          Timestamp: {timestamp}
          <br />
          Environment: {process.env.NODE_ENV}
        </div>
        <h1 className="font-mono text-xl font-semibold text-zinc-800">
          {serverState.exception}
        </h1>
      </div>

      <pre className="mt-6 overflow-auto rounded bg-zinc-900 p-4 font-mono text-sm text-zinc-200">
        {serverState.stack}
      </pre>
    </div>
  );
};

export default Page;
