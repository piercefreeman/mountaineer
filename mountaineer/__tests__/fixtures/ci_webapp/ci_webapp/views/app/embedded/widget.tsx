import React from "react";
import { useServer } from "./_server";

const EmbeddedWidget = ({ label }: { label: string }) => {
  const serverState = useServer({ label });
  const renderedLabel = serverState.label ?? label;
  const embeddedCount = serverState.embedded_count ?? 0;
  const requestPath = serverState.request_path ?? "";

  return (
    <section data-testid="embedded-widget">
      <p>
        Embedded widget: {renderedLabel} on {requestPath}
      </p>
      <p>Embedded count: {embeddedCount}</p>
      <button
        className="rounded-md bg-emerald-600 p-2 text-white"
        onClick={async () => {
          await serverState.increment_embedded_count({ label });
        }}
      >
        Increment embedded
      </button>
    </section>
  );
};

export default EmbeddedWidget;
