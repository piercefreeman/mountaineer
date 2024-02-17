import React, { useState } from "react";
import { useServer } from "./_server/useServer";
import { Action } from "./_server/models";
import { Error } from "../components";
import { classNames } from "../utilities";

const ActionPanel = ({ action }: { action: Action }) => {
  const [showAction, setShowAction] = useState(false);

  const mostRecentResult =
    action.results.length > 0 ? action.results[0] : undefined;
  const conditionalColorScheme = mostRecentResult?.exception
    ? "bg-red-800"
    : "bg-slate-800";

  return (
    <div>
      <div
        className={classNames(
          "cursor-pointer rounded p-4 font-medium text-white",
          conditionalColorScheme,
        )}
        onClick={() => setShowAction((showAction) => !showAction)}
      >
        {action.registry_id}
      </div>
      {showAction && (
        <div className="mt-4 flex">
          {/* Color bar to group action content */}
          <div
            className={classNames("h-auto w-2 rounded", conditionalColorScheme)}
          ></div>
          {/* Main content */}
          <div className="ml-4">
            <div>{action.input_body || "No Input"}</div>
            <div className="mt-4 space-y-4">
              {action.results.map((result) => {
                return (
                  <div key={result.id}>
                    <div className="rounded border border-slate-800 p-4">
                      Attempt {result.attempt_num + 1} @ {result.finished_at}
                    </div>
                    {!result.exception && (
                      <div className="mt-4">{result.result_body || "None"}</div>
                    )}
                    {result.exception && (
                      <Error
                        className="mt-4"
                        title={result.exception}
                        stack={result.exception_stack}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const Page = () => {
  const serverState = useServer();

  return (
    <div>
      <div>
        <a
          className="font-medium text-blue-500"
          href={serverState.linkGenerator.daemonHomeController({})}
        >
          * Go Home
        </a>
      </div>
      <div className="mt-4 rounded border border-slate-800 p-4">
        <p>Launch Time: {serverState.launch_time}</p>
        <p>End Time: {serverState.end_time || "Pending"}</p>
      </div>
      <div className="mt-4">Input: {serverState.input_body}</div>
      {serverState.exception && (
        <Error
          className="mt-4"
          title={serverState.exception}
          stack={serverState.exception_stack}
        />
      )}
      <div className="mt-4 space-y-4">
        {serverState.actions.map((action) => (
          <ActionPanel key={action.id} action={action} />
        ))}
      </div>
    </div>
  );
};

export default Page;
