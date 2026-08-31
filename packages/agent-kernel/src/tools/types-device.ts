import type { ToolInputSchema } from "./types";

/** 设备声明的一个能力 */
export interface DeviceToolSpec {
  name: string;
  description: string;
  /** 省略则视为无参工具 */
  schema?: ToolInputSchema;
}

export type { ToolInputSchema };
