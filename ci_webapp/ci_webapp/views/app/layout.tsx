import React, { ReactNode } from "react";
import { useServer } from "./_server";

const Layout = ({ children }: { children: ReactNode }) => {
  const serverState = useServer();

  return (
    <div>
      <h1>Layout State: {serverState.layout_value}</h1>
      <div>{children}</div>
    </div>
  );
};

export default Layout;
