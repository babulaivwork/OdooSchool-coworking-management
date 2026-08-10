=================================
Odoo School Coworking Management
=================================

Odoo School Coworking Management is an Odoo 19 module for organizing
coworking locations, bookable resources, membership plans, client
memberships, bookings, and visits.

Features
========

* Manage coworking locations, working hours, managers, and staff.
* Maintain desks, meeting rooms, private offices, and event spaces.
* Track available, maintenance, inactive, and archived resources.
* Configure unlimited, hourly, and visit-based membership plans.
* Link each membership plan to one coworking product and use the product sales
  price as the single stored membership price.
* Track client memberships, validity periods, usage limits, renewals, and
  simplified payment status.
* Reserve membership hours or visits when a booking is confirmed.
* Prevent bookings outside working hours, overlapping bookings, and bookings
  of unavailable resources.
* Find available resources with a dedicated wizard.
* Review bookings in list, form, calendar, graph, and pivot views.
* Register check-in and check-out through visits created from confirmed
  bookings.
* Print booking confirmations and membership invoices in PDF format.
* Restrict records by user role and assigned coworking locations.
* Use prepared demo data and automated tests for the implemented workflows.
* Use the module in English or Ukrainian.

Installation
============

#. Copy the ``OdooSchool_coworking_management`` directory to an Odoo 19
   addons path.
#. Add the parent directory to the ``addons_path`` option in the Odoo
   configuration file.
#. Restart the Odoo server.
#. Update the Apps list.
#. Install **Odoo School Coworking Management**.

The module depends on the standard ``base``, ``mail``, ``product``, and
``web`` modules.

Configuration
=============

#. Open **Settings > Users & Companies > Users**.
#. Assign either **Coworking User** or **Coworking Admin** to each employee.
#. Create coworking locations and assign staff members to the locations they
   may access.
#. Configure the company timezone because booking working-hour checks use the
   company timezone, with the current user timezone and UTC as fallbacks.
#. Create membership plans and link each plan to one coworking membership
   product.
#. Configure resources and their operational states for every location.

Roles
=====

Coworking User
--------------

The user can work with operational records for assigned locations, manage
clients, confirm membership payments, activate memberships, create bookings,
and register visits. Archived configuration records are not available.

Coworking Admin
---------------

The administrator inherits the Coworking User role and has full access to all
locations, configuration records, archived records, and delete operations.

Usage
=====

Membership Workflow
-------------------

#. Create a client and enable **Coworking Client**.
#. Create a draft membership and select its membership plan.
#. Use **Mark as Paid** after receiving payment.
#. Use **Activate** to initialize the plan limits.
#. Freeze, unfreeze, or terminate the membership when required.

Only a paid draft membership can be activated. Automatic renewal creates a
new unpaid draft and never activates it automatically. The simplified payment
workflow records only payment status and date; it does not create accounting
entries or online payment transactions. After payment, the client, plan,
location, and start date are locked. A membership with confirmed bookings
cannot be frozen or terminated until those bookings are completed or
cancelled.

Booking and Visit Workflow
--------------------------

#. Open **Coworking > Operations > Find Available Resource** or create a
   booking manually.
#. Select an active membership, resource, and full-hour period.
#. Confirm the booking to reserve the required membership limit.
#. Use **Check In** to create the related visit.
#. Open the visit from the booking smart button and use **Check Out**.

Check-out completes the booking. Cancelling a confirmed booking before
check-in returns its reserved limit. Cancelling an open visit also cancels the
related booking and returns the reservation. Check-in revalidates the current
membership, resource, and location state. A booking cannot be completed by a
direct action before its related visit is checked out.

Reports
=======

* **Booking Confirmation** is available from the booking print menu and shows
  the current booking status, client, resource, location, membership, and
  general coworking rules.
* **Membership Invoice** is available from the membership print menu and uses
  the sales price and currency of the product linked to the selected plan.

Demo Data and Tests
===================

When demo data is enabled, the module creates sample locations, resources,
plans, products, clients, memberships, bookings, visits, and users for both
roles. Automated tests cover every custom model, security rules, constraints,
sequences, the availability wizard, and report rendering.

Known Limitations
=================

* The module uses a simplified payment flag instead of ``sale.order`` and
  ``account.move`` integration.
* Online payment and the customer portal are outside the current project
  scope.
* The current business rules are designed for one company with multiple
  coworking locations.

Credits
=======

Authors
-------

* `Odoo School Student <https://odoo.school/>`_
