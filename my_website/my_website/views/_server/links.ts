import { getLink as HomeControllerGetLinks } from '../app/home/_server/links';
import { getLink as DetailControllerGetLinks } from '../app/detail/_server/links';
import { getLink as ComplexControllerGetLinks } from '../app/complex/_server/links';
const linkGenerator = {
homeController: HomeControllerGetLinks,
detailController: DetailControllerGetLinks,
complexController: ComplexControllerGetLinks
};

export default linkGenerator;