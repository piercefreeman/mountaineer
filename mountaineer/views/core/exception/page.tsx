import React from "react";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();
  const timestamp = new Date().toISOString();

  return (
    <>
      <style>{serverState.formatting_style}</style>
      <style>{`
        .highlight pre {
          line-height: inherit !important;
          }
        `}</style>
      <div className="mx-20 space-y-6 rounded-lg p-8">
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
        <div className="space-y-4">
          <div className="flex items-center space-x-1 text-red-600 font-semibold">
            <span>{serverState.parsed_exception.exc_type}:</span>
            <span>{serverState.parsed_exception.exc_value}</span>
          </div>

          {serverState.parsed_exception.frames.map((frame, index) => (
            <div
              key={index}
              className="border rounded-lg overflow-hidden bg-white"
            >
              {/* File header */}
              <div className="bg-gray-100 px-4 py-2 border-b flex justify-between items-center">
                <div className="font-mono text-sm text-gray-700">
                  {frame.file_name}:{frame.line_number}
                </div>
                <span className="px-3 py-1 bg-blue-500 text-white rounded text-sm">
                  {frame.function_name}
                </span>
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
          ))}
        </div>
      </div>
    </>
  );
};

export default Page;
