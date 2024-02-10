import React, { useState } from "react";
import { useServer } from "./_server/useServer";
import {
  HTTPValidationErrorException,
  SignupInvalidException,
} from "./_server/actions";
import {
  InputComponent,
  ButtonComponent,
  LinkComponent,
  ErrorComponent,
} from "../components";
import { useRecapcha } from "../recaptcha";

const SignupPage = () => {
  const serverState = useServer();

  const [isLoadingSubmit, setIsLoadingSubmit] = useState(false);
  const [signupError, setSignupError] = useState<string | undefined>(undefined);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const recapchaKey =
    serverState.recapcha_enabled && serverState.recapcha_client_key
      ? useRecapcha(serverState.recapcha_client_key)
      : null;

  return (
    <div className="mx-auto max-w-md">
      <h2 className="mt-6 text-center text-3xl font-bold tracking-tight">
        Create a new account
      </h2>
      <div className="mt-2 text-center text-sm text-gray-600">
        If you already have one, login{" "}
        <LinkComponent href={serverState.linkGenerator.loginController({})}>
          here.
        </LinkComponent>
      </div>
      <div className="mt-8 space-y-4 bg-white p-8 shadow">
        {signupError && (
          <ErrorComponent>
            <span>{signupError}</span>
          </ErrorComponent>
        )}
        <InputComponent
          type="email"
          onChange={(e) => {
            setEmail(e.target.value);
          }}
          placeholder="Email"
          value={email}
        />
        <InputComponent
          type="password"
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          value={password}
        />
        <InputComponent
          type="password"
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="Confirm Password"
          value={confirmPassword}
        />
        <ButtonComponent
          disabled={isLoadingSubmit}
          onClick={async () => {
            // Local validation
            if (password !== confirmPassword) {
              setSignupError("Passwords do not match.");
              return;
            }

            setIsLoadingSubmit(true);

            try {
              await serverState.signup({
                requestBody: {
                  username: email,
                  password: password,
                  recapcha_key: recapchaKey,
                },
              });
              setSignupError(undefined);
            } catch (e) {
              if (e instanceof SignupInvalidException) {
                setSignupError(e.body?.invalid_reason);
              } else if (e instanceof HTTPValidationErrorException) {
                setSignupError(e.body?.detail?.[0]?.msg);
              } else {
                throw e;
              }
            } finally {
              setIsLoadingSubmit(false);
            }
          }}
        >
          Register
        </ButtonComponent>
      </div>
      {serverState.recapcha_enabled && (
        <div className="mt-4 px-4 text-xs text-gray-400">
          User registration is protected by reCAPTCHA. Google's{" "}
          <a
            className="text-gray-500"
            href="https://policies.google.com/privacy"
          >
            Privacy Policy
          </a>{" "}
          and{" "}
          <a className="text-gray-500" href="https://policies.google.com/terms">
            Terms of Service
          </a>{" "}
          apply.
        </div>
      )}
    </div>
  );
};

export default SignupPage;
