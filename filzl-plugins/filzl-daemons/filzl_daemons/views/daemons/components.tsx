import React, { ReactNode } from "react";
import { classNames } from "./utilities";

export const Error = ({
  title,
  stack,
  className,
}: {
  title: string;
  stack: string | null;
  className?: string;
}) => {
  return (
    <div
      className={classNames(
        "whitespace-pre-wrap rounded bg-red-50 p-4 text-red-700 ring-1 ring-inset ring-red-600/20",
        className ? className : "",
      )}
    >
      <p className="font-bold">{title}</p>
      <p>{stack}</p>
    </div>
  );
};
