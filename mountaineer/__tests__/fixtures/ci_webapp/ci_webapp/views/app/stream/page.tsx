import React, { useState } from "react";
import { useServer } from "./_server";

const Page = () => {
  const serverState = useServer();
  const [currentStream, setCurrentStream] = useState("");

  return (
    <div>
      <div>Current Stream: {currentStream}</div>
      <div>
        <button
          className="rounded-md bg-blue-500 p-2 text-white"
          onClick={async () => {
            const responseStream = await serverState.stream_action();
            for await (const response of responseStream) {
              setCurrentStream(response.passthrough.value);
            }
          }}
        >
          Start Stream
        </button>
      </div>
    </div>
  );
};

export default Page;
