import { resolveActiveModel, resolveActiveModelP2V2, resolveHistoricalActiveModelP2V1 } from "./active-model";



export class ActiveModelError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ActiveModelError";
  }
}

export { resolveActiveModel, resolveActiveModelP2V2, resolveHistoricalActiveModelP2V1 };

