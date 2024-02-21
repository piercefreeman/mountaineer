import React from "react";

export const InputComponent = (
  props: React.InputHTMLAttributes<HTMLInputElement>,
) => {
  return (
    <input
      {...props}
      className="relative block w-full appearance-none rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-500 focus:z-10 focus:border-blue-500 focus:outline-none focus:ring-blue-500 sm:text-sm"
    />
  );
};

export const ButtonComponent = (
  props: React.ButtonHTMLAttributes<HTMLButtonElement>,
) => {
  return (
    <button
      {...props}
      className="disabled:hover-bg-blue-400 group relative flex w-full cursor-pointer items-center justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-default disabled:bg-blue-300"
    />
  );
};

export const LinkComponent = (
  props: React.AnchorHTMLAttributes<HTMLAnchorElement>,
) => {
  return (
    <a {...props} className="font-medium text-blue-500 hover:text-blue-600" />
  );
};

export const ErrorComponent = ({ children }: { children: React.ReactNode }) => {
  return (
    <div
      className="relative rounded border border-red-400 bg-red-100 px-4 py-3 text-sm text-red-700"
      role="alert"
    >
      {children}
    </div>
  );
};
