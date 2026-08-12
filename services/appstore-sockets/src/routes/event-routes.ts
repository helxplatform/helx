import { Router } from 'express'
import { requirePublishSecret, publisherSecret } from '../config'
import { authenticationMiddleware } from '../middleware'
import { AppStatus, AppStatusEvent, ContainerStatus } from '../events/app-status-events'

const router = Router()
if (requirePublishSecret) {
    console.log('--- Requiring all event uploads to be signed using publisher secret ---')
    router.use(authenticationMiddleware(publisherSecret))
} else {
    console.log('--- Not requiring signed event uploads ---')
}

router.post('/app/status', (req, res) => {
    const getWsClient = req.getWsClient!

    const statusEvent = req.body as AppStatusEvent
    const appId = req.body.app_id
    const systemId = req.body.system_id
    const appOwner = req.body.app_user
    const status = req.body.status
    const reason = req.body.reason
    const containerStates = req.body.container_states

    if (!appId || !appOwner || !status || !Object.keys(AppStatus).includes(status)) {
        res.status(400)
        res.send()
    } else {
        getWsClient(appOwner).emitAppStatus({ appId, systemId, status, reason, containerStates })

        res.status(200)
        res.send()
    }
})

export default router