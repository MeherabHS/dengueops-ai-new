import { randomUUID } from "node:crypto";
import { RequestBodyError } from "@/lib/http/request-body";
import type { RuntimeErrorResponse } from "./contracts";

export class RuntimePublicError extends Error {
  readonly code: string;
  readonly category: RuntimeErrorResponse["error"]["category"];
  readonly statusCode: number;
  readonly retryable: boolean;

  constructor(
    code: string,
    category: RuntimeErrorResponse["error"]["category"],
    message: string,
    statusCode: number,
    retryable = false,
  ) {
    super(message);
    this.name = "RuntimePublicError";
    this.code = code;
    this.category = category;
    this.statusCode = statusCode;
    this.retryable = retryable;
  }
}


export function errorResponse(error: unknown, correlationId = randomUUID()): {
  body: RuntimeErrorResponse;
  status: number;
} {
  if (error instanceof RequestBodyError) {
    return {
      status: error.status,
      body: {
        ok: false,
        error: {
          code: error.code,
          category: "validation",
          message: error.message,
          retryable: false,
          correlationId,
        },
      },
    };
  }
  if (error instanceof RuntimePublicError) {
    return {
      status: error.statusCode,
      body: {
        ok: false,
        error: {
          code: error.code,
          category: error.category,
          message: error.message,
          retryable: error.retryable,
          correlationId,
        },
      },
    };
  }
  return {
    status: 500,
    body: {
      ok: false,
      error: {
        code: "runtime_validation_failed",
        category: "internal",
        message: "Runtime validation could not be completed.",
        retryable: true,
        correlationId,
      },
    },
  };
}
