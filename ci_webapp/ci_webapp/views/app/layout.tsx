import React, { ReactNode } from "react";
import { useServer } from "./_server";

const Layout = ({ children }: { children: ReactNode }) => {
  const serverState = useServer();

  return (
    <div className="p-6">
      <h1>
        Layout State: {serverState.layout_value} : {serverState.layout_arg}
      </h1>
      <div>{children}</div>
      <div>
        <button
          className="rounded-md bg-indigo-500 p-2 text-white"
          onClick={async () => {
            await serverState.increment_layout_value();
          }}
        >
          Layout increment
        </button>
      </div>
    </div>
  );
};

export default Layout;
