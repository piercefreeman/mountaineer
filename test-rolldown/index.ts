// This file will be processed by Rolldown
// The variable below should be replaced by the Define feature
import { greet2 } from "./other";

console.log("The value of MY_VAR is:", process.env.MY_VAR);

// Export a simple function for demonstration
export function greet(): string {
    greet2();
    return `Hello from the environment: ${process.env.MY_VAR}`;
} 