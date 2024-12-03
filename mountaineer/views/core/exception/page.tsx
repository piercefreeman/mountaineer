import React, { useState } from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();
  const [showFrame, setShowFrame] = useState<string | null>(null);
  const timestamp = new Date().toISOString();

  return (
    <>
      <style>{serverState.formatting_style}</style>
      <style>{`
        .highlight pre {
          line-height: inherit !important;
          }
        `}</style>
      <div className="md:mx-20 space-y-6 rounded-lg p-8">
        <div className="space-y-2">
          <div className="text-sm text-zinc-500 font-mono">
            Timestamp: {timestamp}
            <br />
            Environment: {process.env.NODE_ENV}
          </div>
          <h1 className="font-mono text-xl font-semibold text-zinc-800 whitespace-pre-wrap">
            {serverState.exception}
          </h1>
        </div>
        <div className="space-y-4">
          <div className="flex items-center space-x-1 text-red-600 font-semibold whitespace-pre-wrap">
            <span>{serverState.parsed_exception.exc_type}:</span>
            <span>{serverState.parsed_exception.exc_value}</span>
          </div>

          {serverState.parsed_exception.frames.map((frame, index) => (
            <div key={frame.id}>
              <div className="border rounded-lg overflow-hidden bg-white">
                {/* File header */}
                <div className="bg-gray-100 px-4 py-2 border-b flex justify-between items-center">
                  <div className="font-mono text-sm text-gray-700">
                    {frame.file_name}:{frame.line_number}
                  </div>
                  <button
                    onClick={() => {
                      if (showFrame !== frame.id) {
                        setShowFrame(frame.id);
                      } else {
                        setShowFrame(null);
                      }
                    }}
                    className="px-3 py-1 bg-blue-500 hover:bg-blue-600 transition-colors text-white rounded text-sm"
                  >
                    {frame.function_name}
                  </button>
                </div>

                {/* Code section */}
                <div className="flex">
                  {/* Line numbers */}
                  <div className="py-4 px-3 text-right font-mono text-sm bg-gray-50 text-gray-500 select-none border-r">
                    {Array.from(
                      {
                        length: frame.end_line_number - frame.start_line_number,
                      },
                      (_, i) => (
                        <div
                          key={i}
                          className={`leading-6 ${
                            frame.start_line_number + i === frame.line_number
                              ? "bg-red-100 text-red-600 font-semibold px-2 -mx-2"
                              : ""
                          }`}
                        >
                          {frame.start_line_number + i}
                        </div>
                      ),
                    )}
                  </div>

                  {/* Code content */}
                  <div
                    className="flex-1 p-4 overflow-x-auto font-mono text-sm bg-gray-800 !leading-6"
                    dangerouslySetInnerHTML={{ __html: frame.code_context }}
                  />
                </div>
              </div>

              {/* Local variables */}
              {showFrame === frame.id && (
                <div className="mt-4 rounded-lg overflow-hidden border border-gray-200 shadow-sm mb-12">
                  <div className="bg-gray-100 p-4 font-mono text-sm font-bold text-gray-700 border-b flex items-center">
                    <div className="grow">Local Variables</div>
                    <button
                      onClick={() => setShowFrame(null)}
                      className="py-1 px-2 -m-2 hover:bg-gray-500/10 rounded"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={1.5}
                        stroke="currentColor"
                        className="size-6"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M6 18 18 6M6 6l12 12"
                        />
                      </svg>
                    </button>
                  </div>
                  <div className="divide-y divide-gray-200">
                    {Object.entries(frame.local_values).map(([key, html]) => (
                      <div key={key} className="flex">
                        <div className="w-48 shrink-0 bg-gray-50 p-4 font-mono text-sm text-gray-600 border-r">
                          {key}
                        </div>
                        <div
                          className="flex-1 p-4 overflow-x-auto font-mono text-sm bg-gray-700"
                          dangerouslySetInnerHTML={{ __html: html }}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
};

export default Page;
