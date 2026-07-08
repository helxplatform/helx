import { Request, Response, NextFunction } from 'express'
import axios from 'axios'
import { appstoreHost } from '../config'

interface AppstoreIdentity {
    remoteUser: string
    accessToken?: string // Sometimes access token is undefined, but that's not important since we are directly authenticating with the appstore server.
}

// Augment request typings globally to add our injected properties.
// This needs to be optional since the middleware may only be used on certain handlers.
declare global {
    namespace Express {
        interface Request {
            appstoreIdentity?: AppstoreIdentity
        }
    }
}

// We need to authenticate appstore identity here rather than through nginx/ambassador
// because otherwise someone could open a websocket connection directly through ambassador with forged
// auth headers.
export default async (req: Request, res: Response, next: NextFunction) => {
    let remoteUser: string | undefined
    let accessToken: string | undefined
    try {
        const authRes = await axios.get(`http://${ appstoreHost }/auth/`, {
            headers: {
                Cookie: req.headers.cookie
            },
            maxRedirects: 0
        })
        remoteUser = authRes.headers["remote_user"]
        accessToken = authRes.headers["access_token"]
    } catch {}
    // In certain circumstances accecssToken will be undefined, not entirely sure why.
    // E.g. the admin account never seems to have an access token.
    if (remoteUser !== undefined) {
        req.appstoreIdentity = {
            remoteUser,
            accessToken
        }
        next()
    } else {
        console.log(`User authentication rejected by Appstore, rejecting connection to ${ req.url }...`)
        res.status(401)
        res.send(`You aren't authorized to access this route.`)
    }
}