{% if create_stub_files %}
import React, { useState } from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();
  const [text, setText] = useState("");

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8 flex items-center justify-between">
          <h1 className="text-4xl font-light tracking-tight text-gray-900">Task Details</h1>
          <a
            className="inline-flex items-center rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 hover:text-gray-900"
            href={serverState.linkGenerator.homeController({})}
          >
            <svg className="mr-2 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Back to Tasks
          </a>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <div className="mb-6">
            <h2 className="mb-2 text-sm font-medium text-gray-500">Current Description</h2>
            <p className="text-lg text-gray-800">{serverState.description}</p>
          </div>

          <div className="space-y-4">
            <h2 className="text-sm font-medium text-gray-500">Update Description</h2>
            <div className="flex gap-3">
              <input
                className="flex-1 rounded-lg border border-gray-200 px-4 py-2.5 text-gray-800 placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                type="text"
                value={text}
                placeholder="Enter new description..."
                onChange={(e) => setText(e.target.value)}
              />
              <button
                className="inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50"
                onClick={async () => {
                  await serverState.update_text({
                    detail_id: serverState.id,
                    requestBody: {
                      description: text,
                    },
                  });
                  setText("");
                }}
                disabled={!text.trim()}
              >
                <svg className="mr-2 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Update
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Page;
{% endif %}
