from jaxtronomy.LensModel.Profiles import shear, sie, pixelated
from jaxtronomy.Util.util import convert_bool_list

__all__ = ['ProfileListBase']

_SUPPORTED_MODELS = ['SHEAR', 'SHEAR_GAMMA_PSI', 'SIE', 'PIXELATED']


class ProfileListBase(object):
    """Base class for managing lens models in single- or multi-plane lensing."""
    def __init__(self, lens_model_list, lens_redshift_list=None,
                 pixel_x_coords=None, pixel_y_coords=None):
        """Create a ProfileListBase object.

        Parameters
        ----------
        lens_model_list : list of str
            Lens model profile types.
        lens_redshift_list : list of float, optional
            Lens redshifts corresponding to the profiles in `lens_model_list`.

        """
        self._pixel_x_coords, self._pixel_y_coords = pixel_x_coords, pixel_y_coords
        self.func_list = self._load_model_instances(lens_model_list, lens_redshift_list)
        self._num_func = len(self.func_list)
        self._model_list = lens_model_list

    def _load_model_instances(self, lens_model_list, lens_redshift_list=None):
        if lens_redshift_list is None:
            lens_redshift_list = [None] * len(lens_model_list)
        func_list = []
        imported_classes = {}
        for lens_type in lens_model_list:
            # These models require a new instance per profile as certain pre-computations
            # are relevant per individual profile
            if lens_type in ['PIXELATED']:
                lensmodel_class = self._import_class(lens_type)
            else:
                if lens_type not in imported_classes.keys():
                    lensmodel_class = self._import_class(lens_type)
                    imported_classes.update({lens_type: lensmodel_class})
                else:
                    lensmodel_class = imported_classes[lens_type]
            func_list.append(lensmodel_class)
        return func_list

    def _import_class(self, lens_type):
        """Get the lens profile class of the corresponding type."""
        if lens_type == 'SHEAR':
            return shear.Shear()
        elif lens_type == 'SHEAR_GAMMA_PSI':
            return shear.ShearGammaPsi()
        elif lens_type == 'SIE':
            return sie.SIE()
        elif lens_type == 'PIXELATED':
            return pixelated.PixelatedPotential(self._pixel_x_coords, self._pixel_y_coords)
        else:
            err_msg = (f"{lens_type} is not a valid lens model. " +
                       f"Supported types are {_SUPPORTED_MODELS}")
            raise ValueError(err_msg)

    def _bool_list(self, k=None):
        """See `Util.util.convert_bool_list`."""
        return convert_bool_list(n=self._num_func, k=k)

    def set_static(self, kwargs_list):
        """Pre-compute lensing quantities for faster (but fixed) execution."""
        for kwargs, func in zip(kwargs, self.func_list):
            func.set_static(**kwargs)
        return kwargs_list

    def set_dynamic(self):
        """Free the cache of pre-computed quantities from `set_static`.

        This mode recomputes lensing quantities each time a method is called.
        This is the default mode if `set_static` has not been called.

        """
        for func in self.func_list:
            func.set_dynamic()

    @property
    def pixelated_index(self):
        if not hasattr(self, '_pix_idx'):
            try:
                self._pix_idx = self._model_list.index('PIXELATED')
            except ValueError:
                self._pix_idx = None
        return self._pix_idx

    @property
    def pixelated_shape(self):
        if not hasattr(self, '_pix_shape'):
            idx = self.pixelated_index
            if idx is not None:
                if self._pixel_x_coords is None or self._pixel_y_coords is None:
                    raise RuntimeError("There is a 'PIXELATED' light profile but "
                                       "no coordinate arrays have been provided")
                self._pix_shape = (len(self._pixel_x_coords), len(self._pixel_y_coords))
            else:
                self._pix_shape = None
        return self._pix_shape

    @property
    def pixelated_coordinates(self):
        return self._pixel_x_coords, self._pixel_y_coords
