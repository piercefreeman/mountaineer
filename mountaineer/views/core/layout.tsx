import React, { ReactNode } from "react";

const Layout = ({ children }: { children: ReactNode }) => {
  return <div className="p-4 bg-zinc-50">{children}</div>;
};

export default Layout;
