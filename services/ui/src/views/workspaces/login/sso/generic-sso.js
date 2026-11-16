import { LoginOutlined } from '@ant-design/icons'
import { useWorkspacesAPI } from '../../../../contexts'
import { SAMLButton } from './sso-button'


/*
    Button for a login provider the UI has no dedicated button for, such as a
    generic OIDC provider (e.g. Keycloak). Labeled with the provider's name as
    reported by /providers/, it redirects to the provider's login path.
 */
export const GenericSSO = ({ provider, ...props }) => {
    const { api } = useWorkspacesAPI()

    return (
        <SAMLButton
            icon={ <LoginOutlined style={{ fontSize: 20, color: "#ffffff" }} /> }
            background="#1890ff"
            foreground="#ffffff"
            login={ () => api.loginRedirect(provider.url) }
            { ...props }
        >
            { provider.name }
        </SAMLButton>
    )
}
