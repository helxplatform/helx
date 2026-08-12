import { Event } from './event'

export enum AppStatus {
    LAUNCHING = "LAUNCHING",
    LAUNCHED = "LAUNCHED",
    FAILED = "FAILED",
    SUSPENDING = "SUSPENDING",
    TERMINATED = "TERMINATED"
}

interface ContainerState {
    type: "WAITING" | "RUNNING" | "TERMINATED"
}
interface ContainerWaitingState extends ContainerState {
    message?: string
    reason?: string
}
interface ContainerRunningState extends ContainerState {
    started_at?: number
}
interface ContainerTerminatedState extends ContainerState {
    exit_code: number
    started_at?: number
    finished_at?: number
    message?: string
    reason?: string
}
export interface ContainerStatus {
    container_name: string
    container_state: ContainerWaitingState | ContainerRunningState | ContainerTerminatedState
}

export interface AppStatusData {
    appId: string
    systemId: string
    status: AppStatus,
    reason: string | null,
    containerStates: ContainerStatus[] | null
}
export class AppStatusEvent extends Event<AppStatusData> {
    static TYPE = "app_status"
    constructor(data: AppStatusData) {
        super(AppStatusEvent.TYPE, data)
    }
}
export class InitialAppStatusesEvent extends Event<AppStatusEvent[]> {
    static TYPE = "initial_app_statuses"
    constructor(data: AppStatusEvent[]) {
        super(InitialAppStatusesEvent.TYPE, data)
    }
    serialize() {
        return {
            ...super.serialize(),
            data: this.getData().map((event) => event.serialize())
        }
    }
}