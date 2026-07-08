import { Event } from './event'

export class WsReadyEvent extends Event<void> {
    static TYPE = "_confirmReady"
    constructor() {
        super(WsReadyEvent.TYPE)
    }
}