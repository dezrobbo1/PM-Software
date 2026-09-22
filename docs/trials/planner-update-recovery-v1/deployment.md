# Trial deployment and reset

Use the protected Vercel branch/PR Preview built from the exact PR head. Verify the page-visible source/build SHA equals the deployment source SHA before any owner trial-core review.

Select **Start trial** for a pristine approved plan. After the replacement succeeds, this resets the current browser's questionnaire as well as its submitted workspace. Unsaved questionnaire content participates in the discard warning. A failed load retains the existing workspace and answers. The server retains no authoritative workspace and different browser contexts do not share updates.

Use **Save workspace** before refresh, navigation, Start trial, Load example, New project, or Open workspace. Refresh starts from the initial page state. Open the downloaded `.pm-workspace.json` to restore accepted history and approval without silent calculation or approval.

The completion download is available only in the tab that explicitly started the practitioner trial and only after pending workspace actions settle. It contains questionnaire responses and a workspace copy but is not itself the native reopen file. Load example, New project, and Open workspace clear that active-trial classification. A native workspace reopened in a fresh context remains fully usable for persistence verification but cannot be mislabeled as official trial-result evidence. Keep the separately saved native workspace and the original trial tab until completion.

No real participants should be invited during Milestone 1.
