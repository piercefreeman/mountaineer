{% if create_stub_files %}
import React, { useState } from "react";
import { useEffect } from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();
  const [text, setText] = useState("");

  return (
    <div className="p-6">
      <h1 className="text-2xl">Detail Page</h1>
      <a
        className="font-medium text-blue-500"
        href={serverState.linkGenerator.homeController({})}
      >
        Go Home
      </a>
      <div>Current Description: {serverState.description}</div>
      <div>
        <input
          className="border border-gray-300 rounded px-2 py-1 mt-2"
          type="text"
          value={text}
          placeholder="New Description"
          onChange={(e) => setText(e.target.value)}
        />
        <button
          className="ml-2 px-2 py-1 bg-blue-500 text-white rounded"
          onClick={async () => {
            await serverState.update_text({
              detail_id: serverState.id,
              requestBody: {
                description: text,
              },
            });
            setText("");
          }}
        >Update</button>
      </div>
    </div>
  );
};

export default Page;
{% endif %}