import { useState, useEffect, useCallback } from "react";

declare global {
  interface Window {
    grecaptcha: {
      ready: (callback: () => void) => void;
      execute: (
        siteKey: string,
        options: { action: string },
      ) => Promise<string>;
    };
  }
}

export const useRecapcha = (siteKey: string) => {
  const [recaptchaToken, setRecaptchaToken] = useState("");

  const loadRecaptchaScript = () => {
    const script = document.createElement("script");
    script.src = `https://www.google.com/recaptcha/api.js?render=${siteKey}`;
    script.addEventListener("load", initializeRecaptcha);
    document.body.appendChild(script);
  };

  const initializeRecaptcha = useCallback(() => {
    window.grecaptcha.ready(() => {
      window.grecaptcha.execute(siteKey, { action: "submit" }).then((token) => {
        setRecaptchaToken(token);
        console.log("reCAPTCHA token:", token);
      });
    });
  }, [siteKey]);

  useEffect(() => {
    if (!window.grecaptcha) {
      loadRecaptchaScript();
    } else {
      initializeRecaptcha();
    }
  }, [initializeRecaptcha]);

  return recaptchaToken;
};
