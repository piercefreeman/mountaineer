import React from "react";
import { useServer } from "./_server/useServer";
import { Action } from "./_server/models";

const ActionPanel = ({ action }: { action: Action }) => {
  return (
    <div>
      <div>{action.input_body}</div>
      <div>
        {action.results.map((result) => {
          return (
            <div>
              <div>{result.result_body}</div>
              <div>
                {result.exception && (
                  <div className="whitespace-pre-wrap rounded border border-red-500 p-4">
                    <p className="font-bold">{result.exception}</p>
                    <p>{result.exception_stack}</p>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Page = () => {
  const serverState = useServer();

  return (
    <div>
      <div>Input: {serverState.input_body}</div>
      {serverState.exception && (
        <div className="whitespace-pre-wrap rounded border border-red-500 p-4">
          <p className="font-bold">{serverState.exception}</p>
          <p>{serverState.exception_stack}</p>
        </div>
      )}
      <div>
        {serverState.actions.map((action) => (
          <ActionPanel action={action} />
        ))}
      </div>
    </div>
  );
};

export default Page;
